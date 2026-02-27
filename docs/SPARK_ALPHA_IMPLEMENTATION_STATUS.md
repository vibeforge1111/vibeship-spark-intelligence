# Spark Alpha Implementation Status

Last updated: 2026-02-27 (local branch snapshot, sqlite-only packet lookup lock + advisory runtime cleanup)
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
- Added SQLite advisory packet spine module `lib/packet_spine.py`:
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

71. `e5d2123` - `refactor(alpha-pr09/pr10): centralize advisory log paths and switch readers to alpha-first`
- Added shared advisory runtime log-path helper module `lib/advisory_log_paths.py`.
- Migrated runtime readers to the shared alpha-first log default:
  - `lib/carmack_kpi.py`
  - `scripts/advisory_day_trial.py`
  - `scripts/advisory_self_review.py`
  - `scripts/cross_surface_drift_checker.py`
  - `scripts/memory_quality_observatory.py`
  - `scripts/openclaw_realtime_e2e_benchmark.py`
  - `lib/advisory_packet_store.py`
- Kept compatibility lane explicit in advisory diagnostics/reporting where needed.

72. `23ed037` - `refactor(alpha-pr10): update observatory flow references to orchestrator/alpha runtime`
- Updated observatory reverse-engineering and readability narratives to reflect alpha-primary runtime (`advisory_orchestrator` + `advisory_engine_alpha`) instead of legacy engine path wording.
- Updated controlled-delta timestamp comment to reflect alpha/compat log reality.
- Added alpha advisory log to baseline rehydrate target set for cutover-era recovery.

73. `fe9f2bb` - `refactor(alpha-pr10): collapse legacy advisory engine entrypoints into alpha compat shim`
- Replaced legacy heavy runtime entrypoints in `lib/advisory_engine.py` with thin compatibility forwards to alpha runtime:
  - `on_pre_tool(...)` -> `advisory_engine_alpha.on_pre_tool(...)`
  - `on_post_tool(...)` -> `advisory_engine_alpha.on_post_tool(...)`
  - `on_user_prompt(...)` -> `advisory_engine_alpha.on_user_prompt(...)`
- Added explicit compat-forward error telemetry/rejection counters for shim failures.
- Updated `get_engine_status()` to expose alpha runtime status under compat mode.
- Net deletion in legacy runtime surface: ~1k lines removed from `lib/advisory_engine.py`.

74. `6ffa803` - `refactor(alpha-pr09): update advisory tuneables consumer maps for alpha-primary runtime`
- Updated tuneables section consumer mapping in `lib/tuneables_schema.py` for `advisory_engine` to alpha-primary host attribution (`advisory_engine_alpha` + compat shim + emitter).
- Updated observatory deep-dive known hot-reload host list for `advisory_engine` to alpha-primary runtime attribution.
- Keeps config-authority/reporting outputs consistent with current runtime ownership.

75. `de7a70c` - `refactor(alpha-pr10): fix residual observatory advisory-engine path references`
- Updated residual advisory reverse-engineering recommendation pointers from legacy `lib/advisory_engine.py` to alpha/orchestrator runtime hosts.
- Keeps observatory “where to change” guidance aligned with current runtime ownership and avoids stale debugging directions.

76. `02bf620` - `refactor(alpha-pr10): rewrite advisory_engine as compact compatibility module`
- Replaced remaining legacy mega-surface in `lib/advisory_engine.py` with a compact compatibility module:
  - keeps required helper APIs used by tests/tools (`_advice_to_rows*`, `_diagnostics_envelope`, `_ensure_actionability`, `_derive_delivery_badge`, lineage/dedupe helpers, config APIs, rejection telemetry)
  - forwards runtime pre/post/prompt entrypoints to alpha runtime
  - retains compat status/log telemetry surfaces
- File size reduced from ~2436 lines to ~536 lines while preserving regression coverage.

77. `89b2cee` - `refactor(alpha-pr10): remove dead advisory_memory_fusion module and dependent tests`
- Deleted non-runtime advisory memory fusion module `lib/advisory_memory_fusion.py` (no live runtime imports remained).
- Removed obsolete dedicated fusion test suite `tests/test_advisory_memory_fusion.py`.
- Removed distillation transformer cross-test that imported fusion-only readiness helper.
- Simplification impact: ~1k lines removed from dead advisory surface.

78. `18ff784` - `refactor(alpha-pr10): inline deterministic prefetch planner into worker and remove split module`
- Inlined deterministic prefetch planning (`plan_prefetch_jobs`) into `lib/prefetch_worker.py`.
- Deleted `lib/advisory_prefetch_planner.py` (single-consumer split module).
- Regression slice: `pytest tests/test_prefetch_worker.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py -q` -> `9 passed`.

79. `3376cd6` - `refactor(alpha-pr10): fold packet feedback and llm reranker into packet_store and delete split modules`
- Inlined packet feedback/outcome helpers into `lib/advisory_packet_store.py`.
- Inlined packet lookup LLM reranker helpers/config into `lib/advisory_packet_store.py`.
- Deleted split helper modules:
  - `lib/advisory_packet_feedback.py`
  - `lib/advisory_packet_llm_reranker.py`
- Regression slice: `pytest tests/test_advisory_packet_store.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_prefetch_worker.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `159 passed`.

80. `e2eaf3f` - `refactor(alpha-pr09): retire packet lookup llm rerank knobs and simplify config/preference surface`
- Retired packet lookup LLM rerank control surface from packet store config/status paths; relaxed lookup remains deterministic.
- Removed packet lookup LLM tuneables from schema and baseline config:
  - `packet_lookup_llm_enabled`
  - `packet_lookup_llm_provider`
  - `packet_lookup_llm_timeout_s`
  - `packet_lookup_llm_top_k`
  - `packet_lookup_llm_min_candidates`
  - `packet_lookup_llm_context_chars`
  - `packet_lookup_llm_provider_url`
  - `packet_lookup_llm_model`
- Simplified runtime LLM setup/preferences flow by removing packet-lookup LLM preference plumbing.
- Updated observatory advisory reverse-engineering render output to show `packet_sqlite_lookup_enabled` instead of removed rerank knob.
- Regression slice: `pytest tests/test_intelligence_llm_preferences.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py -q` -> `157 passed`.

81. `b0fdd21` - `feat(alpha-observability): track suppression burden across kpi and review reports`
- Added explicit alpha suppression event accounting in KPI scorecard metrics (`lib/carmack_kpi.py`):
  - `alpha_suppressed`
  - `alpha_suppression_events`
  - `suppression_burden`
- Expanded failure snapshot event interest list to include alpha suppression/error outcomes.
- Updated review/controlled-delta summaries to report suppression share and treat suppression-dominant windows as noisy.
- Added focused regression coverage in:
  - `tests/test_carmack_kpi.py`
  - `tests/test_advisory_self_review.py`
- Regression slice: `pytest tests/test_carmack_kpi.py tests/test_advisory_self_review.py -q` -> `9 passed`.

82. `c8e07e2` - `refactor(alpha-pr09): retire packet_rerank llm area and trim config surface`
- Removed packet-level `packet_rerank` LLM rerank step from relaxed advisory candidate lookup.
- Removed `packet_rerank_*` keys from:
  - LLM dispatch registry/defaults
  - LLM prompt catalog
  - tuneables schema
  - baseline config
  - LLM-area observatory host mapping
- Updated LLM dispatch registry tests for reduced area count.
- Regression slice: `pytest tests/test_llm_dispatch.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_intelligence_llm_preferences.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py -q` -> `182 passed`.

83. `e6af80e` - `refactor(alpha-pr09): remove unused drift_diagnose llm area`
- Removed the dead `drift_diagnose` LLM area surface (no active runtime callsite) from:
  - LLM dispatch registry/defaults
  - LLM prompt catalog
  - tuneables schema
  - baseline config
  - LLM-area observatory host mapping
- Updated LLM dispatch registry tests for the new reduced total.
- Regression slice: `pytest tests/test_llm_dispatch.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_intelligence_llm_preferences.py tests/test_cross_surface_drift_checker.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py -q` -> `184 passed`.

84. `75d6aa7` - `refactor(alpha-pr10): stop advisory alpha compat-log mirroring`
- Removed duplicate alpha runtime mirror writes to `~/.spark/advisory_engine.jsonl`.
- Advisory runtime now writes only canonical `~/.spark/advisory_engine_alpha.jsonl`.
- Kept compatibility readers/fallback paths for historical logs while shrinking live write surface.
- Updated alpha log test coverage to assert single-log behavior.
- Regression slice: `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_evidence.py tests/test_advisory_packet_store.py tests/test_advisory_self_review.py tests/test_cross_surface_drift_checker.py tests/test_memory_quality_observatory.py tests/test_carmack_kpi.py tests/test_advisory_day_trial.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `69 passed`.

85. `0bab9b0` - `feat(alpha-pr04): stabilize packet store readiness via refreshable stale window`
- Updated packet-store status scoring to treat recently updated stale packets as refreshable capacity even before first usage.
- Expanded refreshable stale grace horizon to 24h for daily-cycle stability in readiness/freshness gates.
- Added regression coverage for refreshable stale packets with zero usage counters.
- Regression slice: `pytest tests/test_advisory_packet_store.py tests/test_production_loop_gates.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `50 passed`.

86. `86b20af` - `refactor(alpha-pr10): delete legacy advisory compat module and dead tests`
- Deleted `lib/advisory_engine.py` compatibility runtime surface.
- Deleted legacy advisory compat test suites:
  - `tests/test_advisory_engine_evidence.py`
  - `tests/test_advisory_engine_lineage.py`
- Updated remaining ownership references to alpha-primary hosts:
  - `lib/tuneables_schema.py`
  - `lib/observatory/tuneables_deep_dive.py`
  - `scripts/vibeforge.py` evolve presets
  - alpha observatory/packet-store wording now references alpha log only
- Regression slice: `pytest tests/test_vibeforge_helpers.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_advisory_preferences.py tests/test_advisory_self_review.py tests/test_cross_surface_drift_checker.py tests/test_memory_quality_observatory.py tests/test_carmack_kpi.py tests/test_advisory_day_trial.py tests/test_intelligence_llm_preferences.py tests/test_llm_dispatch.py tests/test_production_loop_gates.py tests/test_context_sync_policy.py tests/test_memory_compaction.py tests/test_memory_spine_sqlite.py tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py -q` -> `251 passed`.

87. `bc34195` - `refactor(alpha-pr10): remove legacy alpha-vs-engine compare surface and compat log helper`
- Deleted `scripts/advisory_alpha_quality_report.py` (legacy alpha-vs-engine compare report path).
- Simplified advisory log-path resolution to alpha-only canonical runtime log in `lib/advisory_log_paths.py`.
- Regression + gate evidence:
  - `pytest tests/test_advisory_self_review.py tests/test_cross_surface_drift_checker.py tests/test_advisory_day_trial.py tests/test_memory_quality_observatory.py tests/test_carmack_kpi.py tests/test_advisory_packet_store.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_intelligence_llm_preferences.py tests/test_llm_dispatch.py tests/test_production_loop_gates.py tests/test_context_sync_policy.py tests/test_memory_compaction.py tests/test_memory_spine_sqlite.py tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py tests/test_vibeforge_helpers.py -q` -> `242 passed`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `8`

88. `db65f8d` - `feat(alpha-pr04): enforce sqlite-canonical packet lookups in runtime mode`
- Updated advisory packet lookup behavior:
  - when `PACKET_SQLITE_LOOKUP_ENABLED=true`, exact and relaxed lookups no longer fall back to JSON index/meta paths
  - JSON lookup fallback path remains only for explicit non-sqlite mode (test/legacy compatibility lane)
- Added regression coverage to enforce no-fallback behavior when sqlite lookup is enabled.
- Regression + gate evidence:
  - `pytest tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_production_loop_gates.py -q` -> `168 passed`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `9`

89. `dc8a518` - `refactor(alpha-pr10): remove advisory_engine compat log rehydrate lane`
- Removed obsolete `advisory_engine.jsonl` restore target from `scripts/rehydrate_alpha_baseline.py`.
- Updated controlled-delta log timestamp comment to alpha-log-only wording.
- Regression + gate evidence:
  - `pytest tests/test_rehydrate_alpha_baseline.py tests/test_cross_surface_drift_checker.py tests/test_advisory_self_review.py tests/test_carmack_kpi.py tests/test_advisory_day_trial.py tests/test_memory_quality_observatory.py tests/test_run_alpha_replay_evidence_helpers.py tests/test_spark_alpha_replay_arena.py tests/test_advisory_packet_store.py tests/test_production_loop_gates.py -q` -> `52 passed`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `10`

90. `44420bb` - `refactor(alpha-pr09): retire non-core architecture llm areas`
- Retired non-core architecture LLM areas from dispatch/schema/config surface:
  - `operator_now_synth`
  - `dead_widget_plan`
  - `error_translate`
  - `config_advise`
  - `canary_decide`
  - `canvas_enrich`
- Simplified corresponding helper modules to deterministic behavior (no llm-area dispatch dependency).
- Reduced LLM area registry surface to learning-core only (20 areas total, architecture areas=0).
- Regression + gate evidence:
  - `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0`
  - `pytest tests/test_llm_dispatch.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_observatory_tuneables_deep_dive.py tests/test_observatory_stage7_curriculum_page.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_production_loop_gates.py tests/test_intelligence_llm_preferences.py tests/test_vibeforge_helpers.py -q` -> `208 passed`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `11`

91. `30ea785` - `refactor(alpha-pr04/pr09): lock packet lookup to sqlite canonical path`
- Retired `advisory_packet_store.packet_sqlite_lookup_enabled` from runtime tuneables schema and baseline config.
- Packet lookup path is now unconditionally SQLite-canonical:
  - removed JSON-index fallback branches from exact/relaxed lookup resolution logic
  - removed packet-store config apply/get plumbing for the retired toggle
- Updated observability wording to reflect canonical lookup backend (`lookup_backend=sqlite_canonical`).
- Updated packet-store tests to stop mutating the removed runtime toggle surface.
- Regression + gate evidence:
  - `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0`
  - `pytest tests/test_advisory_packet_store.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_observatory_tuneables_deep_dive.py tests/test_observatory_stage7_curriculum_page.py tests/test_intelligence_llm_preferences.py -q` -> `164 passed`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `12`

92. `132de3d` - `refactor(alpha-pr04): remove dead packet sqlite toggle constant`
- Removed obsolete `PACKET_SQLITE_LOOKUP_ENABLED` module-level constant after lookup path lock to SQLite.
- Keeps packet store runtime surface consistent with schema/config (no retired toggle symbols left in code).
- Regression evidence:
  - `pytest tests/test_advisory_packet_store.py -q` -> `19 passed`

93. `251d2f8` - `refactor(alpha-pr10): collapse advisory orchestrator to alpha shim`
- Replaced orchestrator route/decision machinery with a compact alpha-only compatibility shim:
  - `on_pre_tool`, `on_post_tool`, `on_user_prompt` are direct exports from `lib/advisory_engine_alpha.py`
  - `get_route_status()` remains for callers and now reports alpha canonical log path
- Removed dead route-decision logging surface from runtime (no separate route-decision jsonl path).
- Updated orchestrator tests to assert exported entrypoint identity and alpha-log status contract.
- Regression + gate evidence:
  - `pytest tests/test_advisory_orchestrator.py tests/test_advisory_engine_alpha.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py -q` -> `165 passed`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `13`

94. `857f870` - `refactor(alpha-pr10): remove dead advisory route state and startup toggle`
- Removed unused `SessionState.last_advisory_route` field from advisory session state.
- Removed dead assignment to `last_advisory_route` in alpha pre-tool flow.
- Removed obsolete startup env default for `SPARK_ADVISORY_ROUTE` now that routing is alpha-only.
- Regression + gate evidence:
  - `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_state.py tests/test_advisory_orchestrator.py tests/test_advisory_packet_store.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `48 passed`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `14`

95. `a8b3b2d` - `refactor(alpha-pr10): route hooks and delta workload directly to alpha engine`
- Removed runtime dependency on orchestrator indirection in live hook and delta workload paths:
  - `hooks/observe.py` now calls `lib.advisory_engine_alpha` handlers directly (`on_pre_tool`, `on_post_tool`, `on_user_prompt`)
  - `scripts/advisory_controlled_delta.py` now runs directly against alpha handlers
- Retained a stable route status payload in controlled-delta output (`mode=alpha`, `decision_log=advisory_engine_alpha.jsonl`) without orchestrator dependency.
- Regression + gate evidence:
  - `python -m py_compile hooks/observe.py scripts/advisory_controlled_delta.py` -> pass
  - `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py tests/test_advisory_orchestrator.py -q` -> `165 passed`
  - `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `15`

96. `28391aa` - `refactor(alpha-pr09): retire fallback emit analytics from kpi and review surfaces`
- Removed explicit fallback-only analytics fields from KPI/review reporting surfaces:
  - removed `fallback_burden` metric from `lib/carmack_kpi.py` scorecards
  - removed fallback-burden rendering from `scripts/carmack_kpi_scorecard.py`
  - removed fallback-burden reporting from `scripts/tune_replay.py`
  - removed `fallback_share_pct` from `scripts/advisory_self_review.py` and `scripts/advisory_controlled_delta.py`
- Kept backward compatibility for historical logs by counting legacy `fallback_emit` rows into delivered totals without exposing a dedicated fallback KPI.
- Updated regression tests accordingly:
  - `tests/test_carmack_kpi.py`
  - `tests/test_advisory_self_review.py`
- Regression + gate evidence:
  - `python -m py_compile lib/carmack_kpi.py scripts/carmack_kpi_scorecard.py scripts/tune_replay.py scripts/advisory_self_review.py scripts/advisory_controlled_delta.py` -> pass
  - `pytest tests/test_carmack_kpi.py tests/test_advisory_self_review.py tests/test_advisory_engine_alpha.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_production_loop_gates.py -q` -> `174 passed`
  - `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `16`

97. `4c2e45c` - `refactor(alpha-pr10): remove advisory_orchestrator module and inline alpha replay lane`
- Deleted the final `lib/advisory_orchestrator.py` compatibility shim now that all runtime and script call sites are alpha-direct.
- Updated replay arena champion/challenger import behavior to avoid module dependency on orchestrator while preserving lane labels and scorecard schema.
- Updated observability flow/readability references to point at alpha runtime ownership only.
- Replaced orchestrator-specific test expectations with alpha entrypoint assertions in `tests/test_advisory_orchestrator.py`.
- Regression + gate evidence:
  - `python -m py_compile scripts/spark_alpha_replay_arena.py lib/observatory/readability_pack.py lib/observatory/advisory_reverse_engineering.py tests/test_advisory_orchestrator.py` -> pass
  - `pytest tests/test_advisory_orchestrator.py tests/test_spark_alpha_replay_arena.py tests/test_advisory_engine_alpha.py -q` -> `9 passed`
  - `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `18`

98. `2e04c8f` - `feat(alpha-start): add strict readiness runner and execution plan`
- Added a single-command alpha start readiness pipeline (`scripts/alpha_start_readiness.py`) that executes:
  - production gates
  - replay evidence batch
  - controlled delta smoke
  - alpha core regression slice
- Added report artifact generation for alpha-start runs:
  - `benchmarks/out/alpha_start/alpha_start_readiness_<run_id>.json`
  - `benchmarks/out/alpha_start/alpha_start_readiness_<run_id>.md`
  - latest pointers (`*_latest.json`, `*_latest.md`)
- Added helper tests for parser/csv logic (`tests/test_alpha_start_readiness_helpers.py`).
- Added a new execution plan with explicit done/not-done audit contract and ordered phases (`docs/SPARK_ALPHA_START_EXECUTION_PLAN.md`).
- Regression + gate evidence:
  - `python -m py_compile scripts/alpha_start_readiness.py tests/test_alpha_start_readiness_helpers.py` -> pass
  - `pytest tests/test_alpha_start_readiness_helpers.py -q` -> `3 passed`
  - `python scripts/alpha_start_readiness.py --emit-report --strict` -> `ready=true`
    - production gate: `READY (19/19 passed)`
    - replay evidence: `alpha_win_rate=1.0`, `promotion_pass_rate=1.0`, `runs=4`
    - controlled delta: pass
    - pytest core slice: `242 passed`
    - report: `benchmarks/out/alpha_start/alpha_start_readiness_20260227_144522.json`

99. `a805a92` - `feat(alpha-start): add machine-generated alpha gap audit counters`
- Added `scripts/alpha_gap_audit.py` to emit objective alpha-gap counters and status flags into reproducible artifacts.
- Added helper tests for the gap-audit utility (`tests/test_alpha_gap_audit_helpers.py`).
- Wired the alpha-start execution plan to require gap-audit artifacts each cycle (`docs/SPARK_ALPHA_START_EXECUTION_PLAN.md`).
- Regression + evidence:
  - `python -m py_compile scripts/alpha_gap_audit.py tests/test_alpha_gap_audit_helpers.py` -> pass
  - `pytest tests/test_alpha_gap_audit_helpers.py -q` -> `2 passed`
  - `python scripts/alpha_gap_audit.py` ->
    - `advisory_files=14`
    - `tuneable_sections=40`
    - `tuneable_keys=415`
    - `lib_jsonl_refs=375`
    - `distillation_files=5`
    - `orchestrator_module_present=false`
    - `vibeforge_has_code_evolve_lane=false`
    - report: `benchmarks/out/alpha_start/alpha_gap_audit_20260227_145053.json`

100. `2797d8b` - `feat(alpha-start): add tuneables usage audit for config reduction waves`
- Added `scripts/tuneables_usage_audit.py` to generate schema-key usage telemetry across `lib/scripts/hooks/tests`.
- Added helper tests for key-usage detection logic (`tests/test_tuneables_usage_audit_helpers.py`).
- Wired tuneables usage artifacts into the alpha-start execution plan (`docs/SPARK_ALPHA_START_EXECUTION_PLAN.md`).
- Regression + evidence:
  - `python -m py_compile scripts/tuneables_usage_audit.py tests/test_tuneables_usage_audit_helpers.py` -> pass
  - `pytest tests/test_tuneables_usage_audit_helpers.py -q` -> `2 passed`
  - `python scripts/tuneables_usage_audit.py` ->
    - `sections=40`
    - `keys=415`
    - `hits=7551`
    - `orphan_keys=0` (under current string-usage heuristic)
    - `scanned_files=505`
    - report: `benchmarks/out/alpha_start/tuneables_usage_audit_20260227_145330.json`

101. `1fe7195` - `refactor(alpha-wave1): inline alpha log path and remove advisory_log_paths module`
- Removed `lib/advisory_log_paths.py` and inlined the canonical alpha log path (`~/.spark/advisory_engine_alpha.jsonl`) in active consumers:
  - `lib/advisory_packet_store.py`
  - `lib/carmack_kpi.py`
  - `scripts/advisory_day_trial.py`
  - `scripts/advisory_self_review.py`
  - `scripts/cross_surface_drift_checker.py`
  - `scripts/memory_quality_observatory.py`
  - `scripts/openclaw_realtime_e2e_benchmark.py`
- This is the first Wave-1 advisory-surface compaction step from the reduction-waves plan.
- Regression + gate evidence:
  - `python -m py_compile lib/advisory_packet_store.py lib/carmack_kpi.py scripts/advisory_day_trial.py scripts/advisory_self_review.py scripts/cross_surface_drift_checker.py scripts/memory_quality_observatory.py scripts/openclaw_realtime_e2e_benchmark.py` -> pass
  - `pytest tests/test_advisory_packet_store.py tests/test_carmack_kpi.py tests/test_cross_surface_drift_checker.py tests/test_memory_quality_observatory.py tests/test_advisory_self_review.py tests/test_advisory_day_trial.py -q` -> `35 passed`
  - `python scripts/alpha_start_readiness.py --emit-report --strict` -> `ready=true` (`run_id=20260227_150002`)
    - production gate: `READY (19/19 passed)`
    - replay evidence: `alpha_win_rate=1.0`, `promotion_pass_rate=1.0`, `runs=4`
    - controlled delta: pass
    - pytest core slice: `242 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=13`, `tuneable_keys=415`, `distillation_files=5`, `orchestrator_module_present=false`
  - `python scripts/tuneables_usage_audit.py` -> `sections=40`, `keys=415`, `hits=7551`, `orphan_keys=0`, `scanned_files=504`

102. `fcde9a1` - `refactor(alpha-wave1): migrate advisory parser helpers to runtime_feedback_parser`
- Renamed `lib/advisory_parser.py` -> `lib/runtime_feedback_parser.py` to remove another advisory-prefixed module while preserving helper behavior.
- Updated all callsites:
  - `scripts/advisory_auto_scorer.py`
  - `scripts/advisory_day_trial.py`
  - `tests/test_advisory_auto_scorer.py`
- Regression + gate evidence:
  - `python -m py_compile lib/runtime_feedback_parser.py scripts/advisory_auto_scorer.py scripts/advisory_day_trial.py tests/test_advisory_auto_scorer.py` -> pass
  - `pytest tests/test_advisory_auto_scorer.py tests/test_advisory_day_trial.py -q` -> `6 passed`
  - `python scripts/alpha_start_readiness.py --emit-report --strict` -> `ready=true` (`run_id=20260227_150634`)
    - production gate: `READY (19/19 passed)`
    - replay evidence: `alpha_win_rate=1.0`, `promotion_pass_rate=1.0`, `runs=4`
    - controlled delta: pass
    - pytest core slice: `242 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=12`, `tuneable_keys=415`, `distillation_files=5`, `orchestrator_module_present=false`
  - `python scripts/tuneables_usage_audit.py` -> `sections=40`, `keys=415`, `hits=7551`, `orphan_keys=0`, `scanned_files=504`

103. `7874e55` - `refactor(alpha-wave1): rename advisory_quarantine to runtime_quarantine`
- Renamed `lib/advisory_quarantine.py` -> `lib/runtime_quarantine.py` and updated runtime imports:
  - `lib/advisor.py`
  - `lib/bridge_cycle.py`
  - `lib/validate_and_store.py`
- Kept quarantine sink semantics and storage path unchanged (`~/.spark/advisory_quarantine/advisory_quarantine.jsonl`) to avoid runtime behavior drift.
- Regression + gate evidence:
  - `python -m py_compile lib/runtime_quarantine.py lib/advisor.py lib/bridge_cycle.py lib/validate_and_store.py` -> pass
  - `pytest tests/test_advisor.py tests/test_bridge_cycle_safety.py tests/test_learning_systems_bridge.py tests/test_chip_merger.py tests/test_pr1_config_authority.py -q` -> `139 passed`
  - `python scripts/alpha_start_readiness.py --emit-report --strict` -> `ready=true` (`run_id=20260227_151255`)
    - production gate: `READY (19/19 passed)`
    - replay evidence: `alpha_win_rate=1.0`, `promotion_pass_rate=1.0`, `runs=4`
    - controlled delta: pass
    - pytest core slice: `242 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=11`, `tuneable_keys=415`, `distillation_files=5`, `orchestrator_module_present=false`
  - `python scripts/tuneables_usage_audit.py` -> `sections=40`, `keys=415`, `hits=7551`, `orphan_keys=0`, `scanned_files=504`

104. `e280435` - `feat(alpha-wave2): add external-usage tuneables audit counters`
- Improved `scripts/tuneables_usage_audit.py` to separate schema-self references from external usage by excluding `lib/tuneables_schema.py` in an explicit external scan lane.
- Added new counters:
  - `external_hits`
  - `external_orphan_keys`
  - `external_scanned_files`
- This provides a measurable Wave-2 pruning target based on external usage instead of schema self-reference inflation.
- Regression + evidence:
  - `python -m py_compile scripts/tuneables_usage_audit.py` -> pass
  - `pytest tests/test_tuneables_usage_audit_helpers.py -q` -> `2 passed`
  - `python scripts/tuneables_usage_audit.py` ->
    - `sections=40`
    - `keys=415`
    - `hits=7551`
    - `orphan_keys=0`
    - `external_hits=6976`
    - `external_orphan_keys=91`
    - `scanned_files=504`
    - report: `benchmarks/out/alpha_start/tuneables_usage_audit_20260227_151854.json`

105. `eb4603c` - `refactor(alpha-wave1): rename advisory_intent_taxonomy to runtime_intent_taxonomy`
- Renamed `lib/advisory_intent_taxonomy.py` -> `lib/runtime_intent_taxonomy.py` and updated imports:
  - `lib/advisor.py`
  - `lib/advisory_engine_alpha.py`
  - `tests/test_advisory_intent_taxonomy.py`
- Intent mapping behavior and API (`map_intent`, `map_intent_to_task_plane`, `build_session_context_key`) are unchanged.
- Regression + gate evidence:
  - `python -m py_compile lib/runtime_intent_taxonomy.py lib/advisory_engine_alpha.py lib/advisor.py tests/test_advisory_intent_taxonomy.py` -> pass
  - `pytest tests/test_advisory_intent_taxonomy.py tests/test_advisory_engine_alpha.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py -q` -> `123 passed`
  - `python scripts/alpha_start_readiness.py --emit-report --strict` -> `ready=true` (`run_id=20260227_152237`)
    - production gate: `READY (19/19 passed)`
    - replay evidence: `alpha_win_rate=1.0`, `promotion_pass_rate=1.0`, `runs=4`
    - controlled delta: pass
    - pytest core slice: `242 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=10`, `tuneable_keys=415`, `distillation_files=5`, `orchestrator_module_present=false`
  - `python scripts/tuneables_usage_audit.py` -> `sections=40`, `keys=415`, `external_orphan_keys=91`, `scanned_files=504`

106. `9d020a8` - `feat(alpha-wave3): add jsonl surface audit for store consolidation`
- Added `scripts/jsonl_surface_audit.py` to measure JSONL usage density by file and top-level scope (`lib/scripts/hooks/tests`) for Wave-3 reduction targeting.
- Added helper tests for JSONL-hit detection (`tests/test_jsonl_surface_audit_helpers.py`).
- Regression + evidence:
  - `python -m py_compile scripts/jsonl_surface_audit.py tests/test_jsonl_surface_audit_helpers.py` -> pass
  - `pytest tests/test_jsonl_surface_audit_helpers.py -q` -> `2 passed`
  - `python scripts/jsonl_surface_audit.py` ->
    - `jsonl_hits=735`
    - `files_with_jsonl_hits=136`
    - `scopes_with_hits=4`
    - report: `benchmarks/out/alpha_start/jsonl_surface_audit_20260227_152911.json`
  - `python scripts/alpha_start_readiness.py --emit-report --strict` -> `ready=true` (`run_id=20260227_152921`)
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=10`, `tuneable_keys=415`, `lib_jsonl_refs=376`

107. `fdc3b72` - `refactor(alpha-wave2): prune five retired tuneable keys with migration-safe validation`
- Removed five externally orphaned keys from active schema and baseline config:
  - `advisory_engine.delivery_stale_s`
  - `advisory_engine.global_dedupe_scope`
  - `advisory_engine.actionability_enforce`
  - `auto_tuner.apply_cross_section_recommendations`
  - `auto_tuner.recommendation_sections_allowlist`
- Added retired-key migration handling in `validate_tuneables(...)` so these keys are silently dropped from runtime/user tuneables instead of being reported as unknown-key warnings.
- Regression + gate evidence:
  - `python -m py_compile lib/tuneables_schema.py` -> pass
  - `python -m lib.tuneables_schema` -> `ok=True`, `warnings=0`, `unknown=0`
  - `pytest tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_intelligence_llm_preferences.py tests/test_llm_dispatch.py tests/test_production_loop_gates.py tests/test_observatory_tuneables_deep_dive.py -q` -> `56 passed`
  - `python scripts/alpha_start_readiness.py --emit-report --strict` -> `ready=true` (`run_id=20260227_153728`)
  - `python scripts/alpha_gap_audit.py` -> `tuneable_keys=410`, `advisory_files=10`, `lib_jsonl_refs=376`
  - `python scripts/tuneables_usage_audit.py` -> `keys=410`, `external_orphan_keys=86`

### Runtime/data repairs applied in local Spark state

- `scripts/backfill_context_envelopes.py --apply`
- `scripts/rebind_outcome_traces.py --apply` (rebound 61 strict-window mismatches)
- `scripts/refresh_packet_freshness.py --apply` (refreshed 5 packet freshness windows)
- `scripts/rebind_outcome_traces.py --apply` (additional rebound 1 strict-window mismatch)
- `scripts/refresh_packet_freshness.py --apply` (additional refresh 34 packet freshness windows)
- `scripts/rebind_outcome_traces.py --apply` (recovered additional 36 missing-trace strict-window rows)
- `scripts/memory_spine_parity_gate.py --required-streak 3` (reached parity streak `5/3`)

### Current measured state (latest run)

- `python scripts/alpha_start_readiness.py --emit-report --strict` -> `ready=true` (`run_id=20260227_153728`)
- `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
- replay evidence batch (`seeds=42,77`; `episodes=8,20`) -> `alpha_win_rate=1.0`, `promotion_pass_rate=1.0`, `runs=4`
- alpha core pytest slice in readiness run -> `242 passed`
- `python scripts/alpha_gap_audit.py` -> `advisory_files=10`, `tuneable_keys=410`, `lib_jsonl_refs=376`, `distillation_files=5`, `orchestrator_module_present=false`, `vibeforge_has_code_evolve_lane=false`
- `python scripts/tuneables_usage_audit.py` -> `sections=40`, `keys=410`, `hits=7546`, `orphan_keys=0`, `external_hits=6976`, `external_orphan_keys=86`, `scanned_files=506`
- `python scripts/jsonl_surface_audit.py` -> `jsonl_hits=735`, `files_with_jsonl_hits=136`, `scopes_with_hits=4`
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `18`
- `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
- `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
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
- `python -m py_compile lib/packet_spine.py lib/advisory_packet_store.py` -> pass
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
- `pytest tests/test_advisory_packet_store.py tests/test_advisory_day_trial.py tests/test_advisory_self_review.py tests/test_cross_surface_drift_checker.py tests/test_memory_quality_observatory.py tests/test_carmack_kpi.py -q` -> `31 passed`
- `pytest tests/test_rehydrate_alpha_baseline.py -q` -> `2 passed`
- `pytest tests/test_advisory_engine_evidence.py tests/test_advisory_engine_lineage.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `172 passed`
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`
- `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
- `pytest tests/test_pr1_config_authority.py tests/test_tuneables_alignment.py tests/test_advisory_engine_evidence.py tests/test_advisory_engine_lineage.py -q` -> `34 passed`
- `python -m py_compile lib/observatory/advisory_reverse_engineering.py` -> pass
- `pytest tests/test_advisory_engine_evidence.py tests/test_advisory_engine_lineage.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_advisory_preferences.py tests/test_advisory_self_review.py tests/test_cross_surface_drift_checker.py tests/test_memory_quality_observatory.py tests/test_carmack_kpi.py tests/test_advisory_day_trial.py tests/test_rehydrate_alpha_baseline.py tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py -q` -> `204 passed`
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`
- `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
- `pytest tests/test_distillation_transformer.py tests/test_advisory_engine_evidence.py tests/test_advisory_engine_lineage.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_advisory_preferences.py tests/test_advisory_self_review.py tests/test_cross_surface_drift_checker.py tests/test_memory_quality_observatory.py tests/test_carmack_kpi.py tests/test_advisory_day_trial.py tests/test_rehydrate_alpha_baseline.py tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py -q` -> `277 passed`
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true` (streak `4`)
- `pytest tests/test_advisory_packet_store.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_prefetch_worker.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `159 passed`
- `python -m py_compile lib/advisory_packet_store.py lib/advisory_engine_alpha.py lib/advisory_orchestrator.py lib/prefetch_worker.py scripts/advisory_tag_outcome.py` -> pass
- `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0` (after packet-store consolidation and split-module deletions)
- `pytest tests/test_intelligence_llm_preferences.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py -q` -> `157 passed`
- `python -m py_compile lib/advisory_packet_store.py lib/intelligence_llm_preferences.py lib/observatory/advisory_reverse_engineering.py scripts/intelligence_llm_setup.py` -> pass
- `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0` (after packet lookup LLM rerank knob retirement)
- `pytest tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_evidence.py tests/test_advisory_engine_lineage.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_context_sync_policy.py tests/test_memory_compaction.py tests/test_memory_spine_sqlite.py tests/test_advisory_preferences.py tests/test_advisory_self_review.py tests/test_cross_surface_drift_checker.py tests/test_memory_quality_observatory.py tests/test_carmack_kpi.py tests/test_advisory_day_trial.py tests/test_intelligence_llm_preferences.py -q` -> `221 passed`
- `python scripts/production_loop_report.py` -> `READY (19/19 passed)` (after packet readiness/freshness status stabilization)
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, `eligible_for_cutover=true`, streak `6`
- `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass

Notable metrics now:
- `context.p50`: 230
- `advisory.emit_rate`: 0.194
- `strict_trace_coverage`: 0.7192
- `strict_acted_on_rate`: 0.2581
- `advisory_store_readiness`: 0.519
- `advisory_store_freshness`: 0.519

### Latest reduction delta (2026-02-27, current branch head)

- `python scripts/alpha_gap_audit.py` -> `advisory_files=10`, `tuneable_keys=279`, `lib_jsonl_refs=376`, `lib_jsonl_runtime_refs=269`, `lib_jsonl_runtime_ext_refs=146`, `distillation_files=3`
- `python scripts/tuneables_usage_audit.py` -> `sections=40`, `keys=279`, `orphan_keys=0`, `external_orphan_keys=0`
- `pytest tests/test_llm_dispatch.py tests/test_intelligence_llm_preferences.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `45 passed`
- `pytest tests/test_distillation_refiner_runtime_llm.py tests/test_eidos_distillation_curriculum.py tests/test_observatory_eidos_curriculum_metrics.py tests/test_distillation_advisory.py -q` -> `11 passed`
- `pytest tests/test_pr2_config_authority.py tests/test_tuneables_alignment.py tests/test_remaining_config_authority.py tests/test_opportunity_scanner.py tests/test_observatory_tuneables_deep_dive.py -q` -> `45 passed`
- `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `54`

### Latest advisory collapse delta (2026-02-27, runtime-session-state rename)

- `lib/advisory_state.py` renamed to `lib/runtime_session_state.py` and all runtime/test imports updated
- `python scripts/alpha_gap_audit.py` -> `advisory_files=9`, `tuneable_keys=279`, `distillation_files=3`
- `pytest tests/test_advisory_state.py tests/test_advisory_engine_alpha.py tests/test_advisory_gate_evaluate.py tests/test_advisory_calibration.py tests/test_advisory_orchestrator.py tests/test_advisory_packet_store.py -q` -> `119 passed`
- `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `57`

### Latest advisory collapse delta (2026-02-27, implicit feedback merge)

- Removed `lib/advisory_implicit_feedback.py` and merged its runtime path into `lib/advisory_engine_alpha.py`.
- Updated post-tool path to call in-module `record_implicit_feedback(...)` directly.
- Updated LLM-area host mapping:
  - `lib/observatory/llm_areas_status.py` now maps `implicit_feedback_interpret` to `lib/advisory_engine_alpha.py`.
- Validation:
  - `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_calibration.py tests/test_advisory_gate_evaluate.py -q` -> `93 passed`
  - `pytest tests/test_intelligence_llm_preferences.py -q` -> `1 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=8`, `tuneable_keys=286`, `distillation_files=3`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `60`

### Latest advisory collapse delta (2026-02-27, prefetch worker rename)

- Renamed `lib/advisory_prefetch_worker.py` -> `lib/prefetch_worker.py`.
- Updated alpha-runtime import path:
  - `lib/advisory_engine_alpha.py` now imports `process_prefetch_queue` from `lib/prefetch_worker.py`.
- Updated config observatory/consumer references:
  - `lib/tuneables_schema.py`
  - `lib/observatory/tuneables_deep_dive.py`
- Updated test imports and retained green prefetch/advisory coverage:
  - `tests/test_prefetch_worker.py`
  - `tests/test_packet_prefetch_config_authority.py`
- Validation:
  - `pytest tests/test_prefetch_worker.py tests/test_packet_prefetch_config_authority.py tests/test_advisory_engine_alpha.py tests/test_tuneables_alignment.py -q` -> `9 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=7`, `tuneable_keys=286`, `distillation_files=3`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `61`

### Latest advisory collapse delta (2026-02-27, packet spine rename)

- Renamed `lib/advisory_packet_spine.py` -> `lib/packet_spine.py` to reduce advisory module surface while preserving SQLite spine behavior.
- Updated packet-store + tests to import the renamed module:
  - `lib/advisory_packet_store.py`
  - `tests/test_advisory_packet_store.py`
  - `tests/test_advisory_packet_store_compaction_meta.py`
- Preserved backward compatibility for runtime DB/env resolution in `lib/packet_spine.py`:
  - reads `SPARK_ADVISORY_PACKET_SPINE_DB` (primary), `SPARK_PACKET_SPINE_DB` (fallback)
  - default DB path remains `~/.spark/advisory_packet_spine.db`
- Validation:
  - `pytest tests/test_advisory_packet_store.py tests/test_advisory_packet_store_compaction_meta.py tests/test_advisory_engine_alpha.py tests/test_tuneables_alignment.py -q` -> `25 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=6`, `tuneable_keys=286`, `distillation_files=3`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `67`

### Latest advisory collapse delta (2026-02-27, emitter rename)

- Renamed `lib/advisory_emitter.py` -> `lib/emitter.py` to reduce advisory module surface while preserving emission behavior.
- Updated alpha engine + tests + verification scripts:
  - `lib/advisory_engine_alpha.py` now imports `emit_advisory` from `lib/emitter.py`
  - `tests/test_advisory_calibration.py`
  - `tests/test_pr1_config_authority.py`
  - `scripts/verify_advisory_emissions.py`
- Updated tuneables consumer mapping:
  - `lib/tuneables_schema.py` now tracks `lib/emitter.py` under `advisory_engine`
- Validation:
  - `pytest tests/test_advisory_calibration.py tests/test_pr1_config_authority.py tests/test_advisory_engine_alpha.py tests/test_tuneables_alignment.py -q` -> `86 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=5`, `tuneable_keys=286`, `distillation_files=3`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `68`

### Latest advisory collapse delta (2026-02-27, preferences rename)

- Renamed `lib/advisory_preferences.py` -> `lib/preferences.py` to further reduce advisory module surface.
- Updated integration points:
  - `spark/cli.py`
  - `scripts/advisory_setup.py`
  - `tests/test_advisory_preferences.py`
  - `lib/tuneables_schema.py`
  - `lib/observatory/tuneables_deep_dive.py`
- Validation:
  - `pytest tests/test_advisory_preferences.py tests/test_cli_advisory.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py -q` -> `35 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=4`, `tuneable_keys=286`, `distillation_files=3`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `69`

### Latest compaction unification delta (2026-02-27, packet compaction lane)

- Added packet compaction planner: `lib/packet_compaction.py` (action contract `update/delete/noop`)
- Added packet compaction runner: `scripts/advisory_packet_compaction.py` (`preview/apply`, bounded `--apply-limit`, optional `--apply-updates`)
- Added tests:
  - `tests/test_packet_compaction.py`
  - `tests/test_advisory_packet_compaction_helpers.py`
- Validation:
  - `pytest tests/test_packet_compaction.py tests/test_advisory_packet_compaction_helpers.py -q` -> `5 passed`
  - `python scripts/advisory_packet_compaction.py --candidate-limit 20` -> preview artifact emitted
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `58`

### Latest compaction automation delta (2026-02-27, sync-integrated packet apply lane)

- Added packet-compaction runtime integration in `lib/context_sync.py`:
  - packet compaction now runs inside periodic compaction flow with bounded apply policy
  - supports cooldown + apply caps + optional review updates
  - records packet compaction telemetry in compaction diagnostics payload/state
- Added packet-store public helper APIs for compaction runtime use:
  - `list_packet_meta(...)`
  - `mark_packet_compaction_review(...)`
- Added sync tuneables for bounded packet-compaction runtime control:
  - `sync.packet_compaction_*` keys (enabled/cooldown/apply thresholds)
- Added validation tests:
  - `tests/test_context_sync_policy.py` (new packet-compaction policy/runtime cases)
  - `tests/test_advisory_packet_store_compaction_meta.py`
- Validation:
  - `pytest tests/test_context_sync_policy.py tests/test_packet_compaction.py tests/test_advisory_packet_compaction_helpers.py tests/test_advisory_packet_store_compaction_meta.py -q` -> `16 passed`
  - `pytest tests/test_advisory_packet_store.py -q` -> `19 passed`
  - `python scripts/alpha_gap_audit.py` -> `advisory_files=9`, `tuneable_keys=286`, `distillation_files=3`
  - `python scripts/production_loop_report.py` -> `READY (19/19 passed)`
  - `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> winner `alpha`, `promotion_gate_pass=true`, streak `59`

## Not done yet

These are still pending relative to the broader Simplification/Fast-Track goals:

1. Advisory collapse wave 1 is exceeded (`advisory_files=4`), but final 3-module end-state is not yet implemented.
2. Storage consolidation to single SQLite-first memory/advisory store is partially implemented (cognitive memory is SQLite-canonical; advisory packet lookup is now SQLite-canonical with no runtime JSON lookup fallback mode).
3. Memory compaction engine is partially implemented (ACT-R cognitive compaction + packet compaction preview/apply lane + sync-integrated bounded packet apply lane are in place); deeper unified policy across all advisory/memory stores is still pending.
4. VibeForge goal-directed self-improvement loop is partially implemented (tuneable lane operational with rollback/reset/diff, adaptive proposal ranking, momentum continuation, cycle budget enforcement, benchmark metric support, and blocking benchmark-stage promotion checks; code-evolve lane is still pending).
5. Config reduction wave target was met and then expanded for sync packet-compaction controls (`tuneable_keys=286`); deeper runtime simplification of high-noise sections is still pending.
6. Distillation file-count collapse wave is now met (`distillation_files=3`); end-to-end flow-level unification beyond module surface is still pending.
7. Broad file/function deletion pass is in progress (legacy advisory dual-path test suites + `advisory_memory_fusion.py` + `advisory_prefetch_planner.py` + `advisory_packet_feedback.py` + `advisory_packet_llm_reranker.py` removed); larger legacy advisory/runtime file deletions are still pending.
8. Final migration playbook is now documented (`docs/SPARK_ALPHA_MIGRATION_PLAYBOOK.md`); execution and cutover evidence collection remains ongoing.
9. PR-04 canonical write-path collapse is complete for cognitive insights (SQLite-first + optional mirror compatibility); runtime JSON consumer surface is now `0` and retirement gate is passing (`6/3` streak).
10. PR-05 superseded fallback rank-extension branch deletion is complete, keyword/parser fallback paths are removed, and per-profile/domain weight branching is collapsed to deterministic fusion defaults; broader retrieval simplification outside these branches is still pending.
11. PR-06 alpha ownership expansion for post-tool/user-prompt is complete; broad legacy advisory file removals after canary burn-in are still pending.
12. PR-09 large config pruning target (500+ knobs) is still pending; this pass focused on high-confidence utility dedup, dead fallback removal, removal of unused `dedupe_optimize` + `suppression_triage` llm-area config surfaces, retirement of 8 packet-lookup LLM rerank knobs, and addition of bounded sync packet-compaction controls.

## In progress right now

- No active in-progress patch; PR-07 replay arena is committed and ready for larger-run evidence collection.
