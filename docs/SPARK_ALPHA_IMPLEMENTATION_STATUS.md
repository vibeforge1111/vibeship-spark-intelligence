# Spark Alpha Implementation Status

Last updated: 2026-02-27 (local branch snapshot, alpha runtime decoupling + orchestrator-first observability alignment)
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
- At this stage alpha->engine fallback was retained for rollback safety (later removed in `ca0b106`).
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
- Removed runtime dependence on keyword-based cognitive fallback in the default route.
- Removed runtime dependence on legacy markdown/engine preview advisory parser paths.

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

27. `291d3cb` - `feat(alpha-vibeforge): harden tuneable loop with rollback/reset/diff and adaptive proposals`
- Extended VibeForge CLI with operational commands:
  - `rollback`, `reset`, `diff`
- Added adaptive proposal ranking over recent ledger outcomes (lightweight UCB-style exploration/exploitation).
- Added max-cycle budget enforcement via goal `max_cycles`.
- Added stronger cycle safety behavior:
  - gate readiness required for promotion
  - error-time auto-rollback path when apply/measure fails
  - explicit `error_rolled_back` and `max_cycles_reached` ledger outcomes
- Expanded helper tests for ranking and rollback-row discovery in `tests/test_vibeforge_helpers.py`.

28. `824fb62` - `feat(alpha-vibeforge): add momentum proposal lane with schema-bounded candidates`
- Added momentum proposal generation from recent promoted tuneable moves to continue successful directions.
- Added schema-bound proposal clamping before apply to reduce no-op/invalid candidate attempts.
- Expanded helper tests for momentum candidate generation.

29. `e9a9335` - `feat(alpha-vibeforge): support benchmark metric source via file or command`
- Added benchmark metric resolution in `scripts/vibeforge.py`:
  - file-backed benchmark payloads via metric spec `path`
  - command-refreshed benchmark payloads via metric spec `command`
  - optional JSON parsing from command stdout via `json_from_stdout=true`
- Added per-cycle benchmark payload cache so objective + constraints do not rerun the same benchmark command repeatedly.
- Expanded helper tests for benchmark metric resolution paths.

30. `0976ae4` - `refactor(alpha): remove stale fallback-budget config and observatory surface`
- Removed stale advisory fallback-budget keys from `config/tuneables.json` to match current runtime/schema surface.
- Removed stale fallback-budget references from docs and observatory stage rendering.
- Reduced dead config/docs surface for PR-09 consistency.

31. `a061ca7` - `refactor(alpha-retrieval): delete legacy cognitive keyword and parser fallback paths`
- Deleted keyword fallback branch from cognitive advisory retrieval (`lib/advisor.py`).
- Deleted legacy advisory markdown/engine preview parser fallback paths (`lib/advisory_parser.py`).
- Kept parser API compatibility while making fallback-only parameters inert.

32. `ca0b106` - `refactor(alpha-route): remove orchestrator auto-fallback and default startup route to alpha`
- Removed automatic alpha->engine fallback behavior from `lib/advisory_orchestrator.py` for pre-tool, post-tool, and user-prompt flows.
- Engine path remains available only through explicit route selection (`SPARK_ADVISORY_ROUTE=engine` or canary routing).
- Updated startup defaults in `start_spark.bat` to `SPARK_ADVISORY_ROUTE=alpha`.
- Updated orchestrator tests for no-auto-fallback behavior.

33. `a7562e2` - `refactor(alpha-pr10): remove advisory emitter legacy compatibility shim`
- Removed the legacy `_emit_advisory_compat(...)` shim from `lib/advisory_engine.py`.
- Advisory engine now calls emitter via the canonical keyword-argument path only.
- Updated advisory engine/router tests that monkeypatched old positional-only emitter signatures.

34. `22f56ea` - `refactor(alpha-pr10): drop duplicate route_hint ledger field and harden dual-path test hermeticity`
- Removed duplicate advisory decision ledger field `route_hint` (redundant with `route`).
- Updated dual-path router test harness to isolate advisor recent-delivery files per test temp dir.
- Keeps PR-10 telemetry cleanup while making repeated local test runs deterministic.

35. `1ebbf8f` - `refactor(alpha-pr09): remove dead advisory parser fallback surface and startup quick-fallback flags`
- Removed dead fallback-only parser parameters from `lib/advisory_parser.py`.
- Removed deprecated scorer flag `--include-engine-fallback` from `scripts/advisory_auto_scorer.py`.
- Removed stale startup quick-fallback env defaults from `start_spark.bat`.

36. `665a118` - `feat(alpha-replay): add batch replay evidence runner with aggregate cutover summary`
- Added `scripts/run_alpha_replay_evidence.py` for multi-seed/multi-episode replay batches.
- Added aggregate run summary and artifact emission for cutover evidence review.
- Added helper tests in `tests/test_run_alpha_replay_evidence_helpers.py`.

37. `10136e7` - `feat(alpha-pr04): add JSON-memory consumer audit tool for sqlite retirement planning`
- Added `scripts/memory_json_consumer_audit.py` to inventory direct JSON memory references by token and surface.
- Emits JSON + Markdown reports to `benchmarks/out/memory_spine_audit/`.
- Added helper tests in `tests/test_memory_json_consumer_audit_helpers.py`.

38. `123a558` - `feat(alpha-pr04): add ACT-R style memory compaction planner and runner`
- Added compaction planner core (`lib/memory_compaction.py`) with:
  - activation scoring via temporal decay
  - duplicate grouping
  - explicit action labeling (`update/delete/noop`)
- Added runner `scripts/cognitive_memory_compaction.py` for preview/apply passes with artifact output.
- Added tests in `tests/test_memory_compaction.py`.

39. `5df7ae9` - `feat(alpha-pr08): add benchmark-stage oracle checks to vibeforge promotion gating`
- Added optional `goal.benchmark_checks[]` validation + runtime evaluation in `scripts/vibeforge.py`.
- Benchmark checks execute only after candidate passes cheap gates (`improved + constraints + gates_ready`).
- Blocking benchmark check failures now force rollback; results are recorded in ledger rows.
- Expanded helper coverage in `tests/test_vibeforge_helpers.py`.

40. `f513369` - `refactor(alpha-pr10): remove route-derived provider diagnostics field`
- Removed route-only `provider_path` diagnostic field and helper from `lib/advisory_engine.py`.
- Keeps diagnostic envelope focused on source evidence/session lineage without route-derived duplication.
- Updated diagnostics envelope evidence tests.

41. `74cce2a` - `feat(alpha-pr04): add JSON-consumer retirement gate with streak ledger`
- Added `scripts/memory_json_consumer_gate.py` to convert audit results into streaked cutover readiness decisions.
- Gate supports runtime-hit and total-hit thresholds with optional enforcement mode.
- Added helper tests in `tests/test_memory_json_consumer_gate_helpers.py`.

42. `d81581e` - `feat(alpha-pr04): migrate runtime cognitive readers to sqlite-first snapshot`
- Switched runtime cognitive readers (gates, observatory, advisory memory fusion, auto-tuner) to SQLite-first snapshot helpers.
- Added runtime snapshot tests and audit helper hardening.

43. `00c4306` - `refactor(alpha-pr10): make live advisory orchestration alpha-only`
- Removed live orchestrator route branching and made runtime pre/post/prompt advisory orchestration alpha-only.
- Kept requested-route telemetry for diagnostics while routing all live traffic through alpha.

44. `3572adf` - `feat(alpha-pr04): add periodic cognitive compaction pass in context sync`
- Added cooldown-based periodic compaction (signal dedupe, struggle dedupe, wisdom promotion) in `lib/context_sync.py`.
- Added env controls and diagnostics for compaction cadence.

45. `a02d6a0` - `refactor(alpha-pr09): prune unused source_roles and llm_areas doc config surface`
- Removed unused top-level `source_roles` from `config/tuneables.json`.
- Removed stale `llm_areas._doc` surface from baseline config.

46. `cecea8c` - `refactor(alpha-pr04): disable runtime JSON fallback by default after gate readiness`
- Disabled runtime JSON fallback by default behind explicit opt-in (`SPARK_MEMORY_RUNTIME_JSON_FALLBACK=1`), while keeping pytest compatibility.
- Added test coverage for default-fallback-off behavior.

47. `5cb3c0b` - `feat(alpha-pr04/pr09): collapse runtime JSON surface and schema-workflow evidence`
- Collapsed residual runtime JSON references to a SQLite-first/default-path helper surface.
- Added `workflow_evidence` to tuneables schema and switched `lib/workflow_evidence.py` to config-authority resolution.
- Updated memory quality observatory context stats to SQLite-first runtime snapshot reads.
- Reduced JSON consumer audit to `runtime_hits=2` (from 18 in prior state).

48. `49d2354` - `refactor(alpha-pr10): remove residual requested-route plumbing from orchestrator`
- Removed dead requested-route env/plumbing from `lib/advisory_orchestrator.py`.
- Route decision telemetry now reflects alpha-only routing without canary/requested-route compatibility fields.

49. `853200f` - `feat(alpha-pr04): retire runtime JSON memory fallback and enforce sqlite-only reads`
- Runtime cognitive snapshot reads are now SQLite-only (`load_cognitive_insights_runtime_snapshot` no longer falls back to JSON).
- Updated `CognitiveLearner`/production-gates pathing to keep runtime canonical while preserving non-canonical compatibility lanes for tests/explicit legacy mode.
- JSON consumer audit now reports `runtime_hits=0`.

50. `b08cb77` - `refactor(alpha-pr04): delete dead runtime snapshot coercion after json fallback retirement`
- Removed unused runtime snapshot coercion path from `lib/spark_memory_spine.py`.
- Reduced PR-04 residual dead code after SQLite-only runtime cutover.

51. `49fd5c9` - `refactor(alpha-pr10): collapse legacy post-gate text dedupe into quality filter`
- Removed the standalone post-gate text-signature dedupe pass in `lib/advisory_engine.py`.
- Folded text-signature suppression into `_apply_emission_quality_filters(...)` using one preloaded global dedupe snapshot.
- Removed dead route-only diagnostics envelope threading in advisory engine diagnostics helpers/callers.
- Updated advisory evidence test for the simplified diagnostics envelope API.

52. `1b53c38` - `refactor(alpha-pr10): unify retrieval fusion weights and prune domain weight branches`
- Added a single deterministic semantic fusion-weight baseline in `lib/advisor.py`.
- Removed per-level/per-domain weight branching from default retrieval profiles while preserving explicit override support.
- Pruned domain-profile weight override keys so domain profiles focus on retrieval routing/threshold knobs.

53. `8936beb` - `refactor(alpha-pr10): remove dead global-dedupe helper surface`
- Removed unused runtime helper functions `_global_recently_emitted(...)` and `_global_recently_emitted_text_sig(...)` from `lib/advisory_engine.py`.
- Removed helper-only tests that depended on those dead helpers and kept behavior coverage anchored on `on_pre_tool` dedupe paths.
- Simplified advisory dedupe surface while preserving runtime behavior.

54. `64c1f69` - `refactor(alpha-pr10): make global dedupe scope deterministic`
- Removed LLM-assisted global dedupe scope optimization from runtime.
- `_dedupe_scope_key(...)` now resolves global scope deterministically to `"global"` (tree/contextual modes unchanged).
- Deleted dead `_llm_area_dedupe_optimize(...)` implementation from `lib/advisory_engine.py`.

55. `5ab1d92` - `refactor(alpha-pr09): remove unused dedupe_optimize llm-area surface`
- Removed the unused `dedupe_optimize` area from the LLM dispatch registry/defaults and prompt catalog.
- Removed `dedupe_optimize_*` keys from tuneables schema and baseline `config/tuneables.json`.
- Updated LLM-areas observatory host mapping to drop the removed area.

56. `dec4978` - `refactor(alpha-pr09): remove unused suppression_triage llm-area surface`
- Removed the unused `suppression_triage` area from advisory runtime, LLM dispatch/defaults, prompt catalog, tuneables schema, and baseline config.
- Further reduced architecture LLM-area surface and config authority footprint without changing advisory behavior.

57. `5bcded9` - `feat(alpha-pr04): run bounded ACT-R compaction in periodic context sync`
- Added runtime ACT-R compaction integration in `lib/context_sync.py`:
  - builds a compaction plan from live cognitive insights
  - applies bounded stale-low-activation deletes per run
  - records delete/update candidate counts + applied deletions in compaction state
- Added env controls:
  - `SPARK_COGNITIVE_ACTR_COMPACTION_ENABLED`
  - `SPARK_COGNITIVE_ACTR_MAX_AGE_DAYS`
  - `SPARK_COGNITIVE_ACTR_MIN_ACTIVATION`
  - `SPARK_COGNITIVE_ACTR_MAX_DELETES`
- Added policy tests for bounded ACT-R deletion behavior in `tests/test_context_sync_policy.py`.

58. `48223e5` - `refactor(alpha-pr10): decouple implicit feedback loop from legacy advisory engine`
- Extracted implicit feedback loop into shared module `lib/advisory_implicit_feedback.py`.
- `advisory_engine_alpha` post-tool path now calls shared `record_implicit_feedback(...)` directly, removing alpha's runtime dependency on `lib/advisory_engine.py`.
- Kept legacy-engine compatibility by alias-importing `_record_implicit_feedback` from the shared module.
- Updated LLM-area observatory host mapping for `implicit_feedback_interpret` to the new module.

59. `e12e3a5` - `feat(alpha-pr05): add readiness-aware relaxed packet lookup scoring`
- Added readiness-aware scoring/flooring in `lib/advisory_packet_store.py` relaxed lookup:
  - packet candidates now include readiness bonus in match score
  - low-readiness packet candidates are filtered before ranking
  - candidate payload now exposes `readiness_score` for diagnostics
- Added packet-store tests for readiness-floor behavior in `tests/test_advisory_packet_store.py`.

60. `de6222c` - `refactor(alpha-pr05): make relaxed candidate lookup miss-path deterministic`
- Standardized miss-path semantics in packet lookup:
  - `lookup_relaxed(...)` returns `None` on miss
  - `lookup_relaxed_candidates(...)` returns `[]` on miss
- Added explicit packet-store regression coverage for candidate miss semantics.

61. `75dbe34` - `refactor(alpha-pr09): remove dead packet-store llm alias globals`
- Removed unused packet-store module globals:
  - `PACKET_LOOKUP_LLM_ENABLED`
  - `PACKET_LOOKUP_LLM_PROVIDER`
  - `PACKET_LOOKUP_LLM_FALLBACK_TO_SCORING`
- Packet-store now relies solely on canonical LLM reranker module state for lookup LLM controls.

62. `7418601` - `feat(alpha-pr04): add sqlite advisory packet spine and lookup integration`
- Added SQLite advisory packet spine module `lib/advisory_packet_spine.py`:
  - metadata upsert path
  - exact-key alias table
  - relaxed candidate query path
- Integrated packet-store with SQLite spine (default-on outside pytest):
  - `save_packet(...)` dual-writes packet metadata + exact alias to SQLite spine
  - `lookup_exact(...)` resolves via SQLite alias first, then JSON index fallback
  - `lookup_relaxed_candidates(...)` queries SQLite candidates first, then JSON meta fallback
- Added config-authority knob `advisory_packet_store.packet_sqlite_lookup_enabled` in schema + baseline config.
- Added packet-store tests for SQLite exact/relaxed lookup behavior when JSON index surfaces are missing.

63. `cd630ae` - `test(alpha-pr09): remove legacy dual-path advisory engine test suites`
- Deleted legacy mock-heavy advisory test suites tied to retired dual-path behavior:
  - `tests/test_advisory_dual_path_router.py`
  - `tests/test_advisory_engine_dedupe.py`
  - `tests/test_advisory_engine_on_pre_tool.py`
- Coverage focus shifted to alpha/orchestrator/evidence/lineage + packet/advisor retrieval paths.

64. `85bafb1` - `refactor(alpha-pr10): route advisory controlled-delta workload through alpha orchestrator`
- Updated `scripts/advisory_controlled_delta.py` to call:
  - `lib.advisory_orchestrator.on_user_prompt`
  - `lib.advisory_orchestrator.on_pre_tool`
  - `lib.advisory_orchestrator.on_post_tool`
- Removed direct workload dependence on legacy `lib.advisory_engine` execution path.
- Script summary now reports `advisory_route` status instead of legacy engine config dump.

65. `ae424ee` - `refactor(alpha-pr07): align replay arena champion route to orchestrator`
- Updated `scripts/spark_alpha_replay_arena.py` champion route from legacy-engine naming to `orchestrator`.
- Replay now compares:
  - champion: `lib.advisory_orchestrator.on_pre_tool`
  - challenger: `lib.advisory_engine_alpha.on_pre_tool`
- Updated replay output/report fields from `legacy_*` to `orchestrator_*`.
- Updated replay evidence helper test expectations for winner labels.

66. `68750f4` - `feat(alpha-pr06): mirror alpha events to advisory_engine compat log`
- Added alpha compatibility mirror in `lib/advisory_engine_alpha.py`:
  - writes to `~/.spark/advisory_engine_alpha.jsonl` (primary)
  - mirrors to `~/.spark/advisory_engine.jsonl` (compat) by default outside pytest
- Added env kill-switch `SPARK_ADVISORY_ALPHA_COMPAT_ENGINE_LOG=0`.
- Added alpha test coverage for compat mirroring behavior.

67. `abeafae` - `docs(alpha): add executable migration playbook`
- Added `docs/SPARK_ALPHA_MIGRATION_PLAYBOOK.md` with:
  - preconditions/gates
  - phased runtime/storage/deletion rollout steps
  - explicit rollback per phase
  - post-merge watch protocol

68. `c694d3a` - `refactor(alpha-pr10): move quality uplift runtime hot-apply to alpha config APIs`
- Added alpha runtime config/status APIs in `lib/advisory_engine_alpha.py`:
  - `apply_alpha_config(...)`
  - `get_alpha_config()`
  - `get_alpha_status()`
- Added advisory-engine section hot-reload registration for alpha runtime config.
- Rewired `lib/advisory_preferences.py` quality uplift hot-apply path to alpha runtime APIs (removed direct runtime dependency on `lib/advisory_engine`).
- Updated preference tests to patch alpha config/status APIs.

69. `b221640` - `refactor(alpha-pr10): align replay and observability to orchestrator-first alpha logs`
- Updated replay arena internals to use orchestrator-first naming in runtime variables (removed residual `legacy_*` internal naming).
- Updated advisory controlled-delta repo-mode targets to alpha/orchestrator files.
- Updated observability/runtime consumers to prefer `~/.spark/advisory_engine_alpha.jsonl` with compat fallback:
  - `scripts/advisory_day_trial.py`
  - `scripts/advisory_self_review.py`
  - `scripts/cross_surface_drift_checker.py`
  - `scripts/memory_quality_observatory.py`
  - `lib/carmack_kpi.py`

70. `068203b` - `refactor(alpha-pr09): make doctor advisory runtime check alpha-first`
- Updated doctor advisory runtime check to prefer `SPARK_ADVISORY_ALPHA_ENABLED` and only use `SPARK_ADVISORY_ENGINE` as legacy alias fallback.
- Updated doctor pass/warn messages to reflect alpha-primary runtime semantics.

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
- `pytest tests/test_memory_json_consumer_audit_helpers.py -q` -> `2 passed`
- `pytest tests/test_memory_compaction.py -q` -> `5 passed`
- `pytest tests/test_memory_json_consumer_gate_helpers.py -q` -> `2 passed`
- `pytest tests/test_advisory_engine_evidence.py -q` -> `13 passed`
- `pytest tests/test_run_alpha_replay_evidence_helpers.py -q` -> `2 passed`
- `pytest tests/test_vibeforge_helpers.py -q` -> `10 passed`
- `pytest tests/test_vibeforge_helpers.py tests/test_tuneables_alignment.py -q` -> `9 passed`
- `pytest tests/test_advisory_orchestrator.py tests/test_advisory_dual_path_router.py tests/test_advisory_engine_alpha.py -q` -> `16 passed`
- `pytest tests/test_advisory_dual_path_router.py tests/test_advisory_engine_dedupe.py tests/test_advisory_engine_on_pre_tool.py -q` -> `31 passed`
- `python scripts/cognitive_memory_compaction.py --candidate-limit 5` -> preview produced compaction report (`total=72`, `update_candidates=12`)
- `python scripts/memory_json_consumer_audit.py --out-dir benchmarks/out/memory_spine_audit` -> audit report refreshed (`hits=64`, `runtime_hits=0`)
- `python scripts/memory_json_consumer_gate.py --max-runtime-hits 0 --max-total-hits 80 --required-streak 3` -> gate pass, streak `6/3`, `ready_for_runtime_json_retirement=true`
- `pytest tests/test_workflow_evidence.py tests/test_production_loop_gates.py tests/test_memory_spine_sqlite.py tests/test_memory_json_consumer_audit_helpers.py tests/test_observatory_helpfulness_explorer.py tests/test_observatory_meta_ralph_totals.py tests/test_context_sync_policy.py -q` -> `44 passed`
- `pytest tests/test_tuneables_alignment.py tests/test_advisor.py -q` -> `98 passed`
- `pytest tests/test_memory_spine_sqlite.py tests/test_production_loop_gates.py tests/test_cognitive_learner.py tests/test_cognitive_emotion_capture.py tests/test_validation_loop.py -q` -> `95 passed`
- `pytest tests/test_advisory_orchestrator.py tests/test_advisory_engine_alpha.py tests/test_advisory_dual_path_router.py tests/test_workflow_evidence.py tests/test_tuneables_alignment.py -q` -> `31 passed`
- `pytest tests/test_advisory_engine_dedupe.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_engine_evidence.py tests/test_advisory_orchestrator.py tests/test_advisory_dual_path_router.py tests/test_advisory_engine_alpha.py -q` -> `49 passed`
- `pytest tests/test_advisory_engine_dedupe.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_engine_lineage.py tests/test_advisory_engine_evidence.py tests/test_advisory_dual_path_router.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_alpha.py -q` -> `48 passed`
- `pytest tests/test_advisory_engine_dedupe.py tests/test_advisory_engine_lineage.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_engine_evidence.py tests/test_advisory_dual_path_router.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_alpha.py -q` -> `48 passed`
- `pytest tests/test_context_sync_policy.py -q` -> `7 passed`
- `pytest tests/test_memory_compaction.py tests/test_memory_spine_sqlite.py tests/test_cognitive_learner.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_tuneables_alignment.py -q` -> `93 passed`
- `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_engine_evidence.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_orchestrator.py tests/test_advisory_dual_path_router.py tests/test_context_sync_policy.py -q` -> `41 passed`
- `python -m py_compile lib/advisory_implicit_feedback.py lib/advisory_engine.py lib/advisory_engine_alpha.py lib/observatory/llm_areas_status.py` -> pass
- `pytest tests/test_advisory_packet_store.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_tuneables_alignment.py -q` -> `19 passed`
- `pytest tests/test_advisor.py tests/test_advisor_retrieval_routing.py -q` -> `116 passed`
- `python -m py_compile lib/advisory_packet_store.py tests/test_advisory_packet_store.py` -> pass
- `pytest tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py -q` -> `130 passed`
- `pytest tests/test_advisory_packet_store.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `32 passed`
- `python -m py_compile lib/advisory_packet_store.py` -> pass
- `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0` (after sqlite packet-spine config integration)
- `pytest tests/test_advisory_packet_store.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py -q` -> `155 passed`
- `python -m py_compile lib/advisory_packet_spine.py lib/advisory_packet_store.py` -> pass
- `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_evidence.py tests/test_advisory_engine_lineage.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `171 passed`
- `python -m py_compile scripts/advisory_controlled_delta.py` -> pass
- `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
- `python -m py_compile scripts/spark_alpha_replay_arena.py scripts/run_alpha_replay_evidence.py` -> pass
- `pytest tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py -q` -> `6 passed`
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> pass
- `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_evidence.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `169 passed`
- `python -m py_compile lib/advisory_engine_alpha.py tests/test_advisory_engine_alpha.py` -> pass
- `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0` (after dedupe_optimize llm-area surface removal)
- `pytest tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_vibeforge_helpers.py tests/test_advisory_engine_dedupe.py tests/test_advisory_engine_lineage.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_engine_evidence.py tests/test_advisory_dual_path_router.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_alpha.py -q` -> `76 passed`
- `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0` (after suppression_triage llm-area surface removal)
- `pytest tests/test_advisor_retrieval_routing.py tests/test_advisor.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `134 passed`
- `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0` (workflow_evidence section now schema-covered)
- `python scripts/spark_alpha_replay_arena.py --episodes 20 --seed 42` -> alpha winner, promotion gate pass, streak reached `22/3`
- Replay artifacts:
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_20260227_013933.json`
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_20260227_013933.md`
  - `benchmarks/out/replay_arena/spark_alpha_replay_scorecards_20260227_013933.json`
  - `benchmarks/out/replay_arena/spark_alpha_replay_arena_diff_20260227_013933.json`
- `pytest tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_evidence.py tests/test_advisory_engine_lineage.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_context_sync_policy.py tests/test_memory_compaction.py tests/test_memory_spine_sqlite.py tests/test_advisory_preferences.py tests/test_advisory_self_review.py tests/test_cross_surface_drift_checker.py tests/test_memory_quality_observatory.py tests/test_carmack_kpi.py tests/test_advisory_day_trial.py -q` -> `220 passed`
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`
- `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass

Notable metrics now:
- `context.p50`: 230
- `advisory.emit_rate`: 0.194
- `strict_trace_coverage`: 0.7192
- `strict_acted_on_rate`: 0.2581
- `advisory_store_readiness`: 0.519
- `advisory_store_freshness`: 0.519

## Not done yet

These are still pending relative to the broader Simplification/Fast-Track goals:

1. Full advisory collapse (17 modules -> compact 3-module architecture) is not implemented.
2. Storage consolidation to single SQLite-first memory/advisory store is partially implemented (cognitive memory is SQLite-canonical; advisory packet metadata now has SQLite spine + default lookup integration with JSON fallback still retained).
3. Memory compaction engine is partially implemented (ACT-R style planner + preview/apply runner + bounded periodic ACT-R runtime compaction for cognitive insights are in place); broader integration across advisory stores is still pending.
4. VibeForge goal-directed self-improvement loop is partially implemented (tuneable lane operational with rollback/reset/diff, adaptive proposal ranking, momentum continuation, cycle budget enforcement, benchmark metric support, and blocking benchmark-stage promotion checks; code-evolve lane is still pending).
5. Large config surface reduction (hard pruning to minimal knobs) is not implemented.
6. Distillation pipeline collapse to minimal observe->filter->score->store->promote flow is not implemented.
7. Broad file/function deletion pass is in progress (legacy advisory dual-path test suites removed); larger legacy advisory/runtime file deletions are still pending.
8. Final migration playbook is now documented (`docs/SPARK_ALPHA_MIGRATION_PLAYBOOK.md`); execution and cutover evidence collection remains ongoing.
9. PR-04 canonical write-path collapse is complete for cognitive insights (SQLite-first + optional mirror compatibility); runtime JSON consumer surface is now `0` and retirement gate is passing (`6/3` streak).
10. PR-05 superseded fallback rank-extension branch deletion is complete, keyword/parser fallback paths are removed, and per-profile/domain weight branching is collapsed to deterministic fusion defaults; broader retrieval simplification outside these branches is still pending.
11. PR-06 alpha ownership expansion for post-tool/user-prompt is complete; broad legacy advisory file removals after canary burn-in are still pending.
12. PR-09 large config pruning target (500+ knobs) is still pending; this pass focused on high-confidence utility dedup, dead fallback removal, and removal of unused `dedupe_optimize` + `suppression_triage` llm-area config surfaces.

## In progress right now

- No active in-progress patch; PR-07 replay arena is committed and ready for larger-run evidence collection.
