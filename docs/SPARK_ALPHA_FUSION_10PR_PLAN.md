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
21. `f324e32` retrieval collapse: semantic-first cognitive path
22. `7b69e46` PR-04 follow-up: parity streak ledger gate tool
23. `a29a5d4` PR-04 promotion: cognitive learner moved to SQLite-canonical mode with JSON mirror compatibility
24. `dede8a5` PR-05 follow-up: removed superseded fallback rank-extension branch in retrieval prefilter
25. `687d965` PR-06 follow-up: alpha-native post-tool and user-prompt handlers (legacy delegation removed)
26. `a7ec9bb` PR-08 start: VibeForge loop CLI skeleton (`init/status/run-once/run/history/pause/resume`)
27. `291d3cb` PR-08 hardening: tuneable loop gets adaptive proposer ranking + `rollback/reset/diff` + cycle budget enforcement
28. `824fb62` PR-08 follow-up: momentum proposer extension + schema-bounded candidate values
29. `e9a9335` PR-08 follow-up: benchmark metric source support (`path` or `command` + stdout JSON)
30. `0976ae4` PR-09 follow-up: stale fallback-budget config/docs/observatory surface removed
31. `a061ca7` PR-10/PR-05 follow-up: deleted keyword cognitive fallback + legacy parser fallback paths
32. `ca0b106` PR-10 follow-up: removed orchestrator auto-fallback and set startup route default to alpha
33. `a7562e2` PR-10 follow-up: removed advisory-emitter legacy compatibility shim in engine
34. `22f56ea` PR-10 follow-up: removed duplicate `route_hint` ledger field and hardened dual-path test hermeticity
35. `1ebbf8f` PR-09 follow-up: removed dead parser fallback scorer/startup control surface
36. `665a118` PR-07 follow-up: added batch replay evidence runner with aggregate summaries
37. `10136e7` PR-04 follow-up: added JSON memory consumer audit report tool
38. `123a558` PR-04 follow-up: added ACT-R style memory compaction planner + runner
39. `5df7ae9` PR-08 follow-up: added blocking benchmark-stage checks to VibeForge promotion gating
40. `f513369` PR-10 follow-up: removed route-derived provider diagnostics field in advisory engine
41. `74cce2a` PR-04 follow-up: added JSON-consumer retirement streak gate ledger
42. `d81581e` PR-04 follow-up: migrated runtime cognitive readers to SQLite-first snapshot
43. `00c4306` PR-10 follow-up: made live advisory orchestration alpha-only
44. `3572adf` PR-04 follow-up: added periodic cognitive compaction pass in context sync
45. `a02d6a0` PR-09 follow-up: pruned unused source_roles and llm_areas doc config surface
46. `cecea8c` PR-04 follow-up: disabled runtime JSON fallback by default after gate readiness
47. `5cb3c0b` PR-04/09 follow-up: collapsed runtime JSON surface and added workflow_evidence schema/config-authority path
48. `49d2354` PR-10 follow-up: removed residual requested-route plumbing from orchestrator
49. `853200f` PR-04 follow-up: retired runtime JSON memory fallback and enforced SQLite-only runtime reads
50. `b08cb77` PR-04 follow-up: deleted dead runtime snapshot coercion path after fallback retirement
51. `49fd5c9` PR-10 follow-up: collapsed standalone post-gate text dedupe into emission-quality filter and removed dead diagnostics route threading
52. `1b53c38` PR-10/PR-05 follow-up: unified retrieval fusion weights and pruned per-domain weight branches in advisor defaults
53. `8936beb` PR-10 follow-up: removed dead global-dedupe helper functions and helper-only tests
54. `64c1f69` PR-10 follow-up: removed LLM-assisted global dedupe scope optimization from runtime (deterministic global scope)
55. `5ab1d92` PR-09 follow-up: removed unused `dedupe_optimize` LLM-area surface (dispatch + schema + baseline tuneables)
56. `dec4978` PR-09 follow-up: removed unused `suppression_triage` LLM-area surface (runtime + dispatch + schema + baseline tuneables)
57. `5bcded9` PR-04 follow-up: integrated bounded ACT-R compaction into periodic runtime context sync with explicit env caps and policy tests
58. `48223e5` PR-10 follow-up: extracted implicit-feedback loop into shared module and removed alpha route dependency on legacy advisory_engine internals
59. `e12e3a5` PR-05 follow-up: added readiness-aware relaxed packet lookup scoring/flooring and candidate readiness diagnostics
60. `de6222c` PR-05 follow-up: made packet lookup miss-path contracts deterministic (`lookup_relaxed -> None`, `lookup_relaxed_candidates -> []`)
61. `75dbe34` PR-09 follow-up: removed dead packet-store LLM alias globals to reduce duplicated config surface
62. `7418601` PR-04 follow-up: added SQLite advisory packet spine and integrated exact/relaxed packet lookup with JSON fallback safety
63. `cd630ae` PR-09 follow-up: removed legacy dual-path advisory engine test suites to reduce obsolete mock-heavy coverage surface
64. `85bafb1` PR-10 follow-up: moved advisory controlled-delta workload execution to alpha orchestrator entrypoints
65. `ae424ee` PR-07 follow-up: updated replay arena champion route to orchestrator and renamed legacy score fields accordingly

Current measured state:
1. `production_loop_report.py`: `READY (19/19 passed)`
2. `memory_quality_observatory.py`: retrieval guardrails passing
3. Key metrics: `context.p50=230`, `advisory.emit_rate=0.194`, `strict_trace_coverage=0.7172`
4. Replay arena latest (`scripts/spark_alpha_replay_arena.py --episodes 20 --seed 42`):
   - winner: `alpha`
   - `promotion_gate_pass=true`
   - `consecutive_pass_streak=22`
5. JSON consumer retirement latest (`scripts/memory_json_consumer_gate.py --max-runtime-hits 0 --max-total-hits 80 --required-streak 3`):
   - `runtime_hits=0`
   - `total_hits=64`
   - `ready_for_runtime_json_retirement=true`
6. Tuneables schema validation: `ok=True`, `unknown=0` (workflow_evidence now schema-covered)
7. Advisory legacy+dedupe test slice (`tests/test_advisory_engine_dedupe.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_engine_evidence.py tests/test_advisory_orchestrator.py tests/test_advisory_dual_path_router.py tests/test_advisory_engine_alpha.py`): `49 passed`
8. Retrieval+config slice (`tests/test_advisor_retrieval_routing.py tests/test_advisor.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py`): `134 passed`
9. Advisory dedupe/lineage slice (`tests/test_advisory_engine_dedupe.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_engine_lineage.py tests/test_advisory_engine_evidence.py tests/test_advisory_dual_path_router.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_alpha.py`): `48 passed`
10. Advisory dedupe deterministic-scope slice (`tests/test_advisory_engine_dedupe.py tests/test_advisory_engine_lineage.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_engine_evidence.py tests/test_advisory_dual_path_router.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_alpha.py`): `48 passed`
11. Config-authority + advisory regression slice after llm-area surface pruning: `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0`; `pytest ...` composite slice -> `76 passed`
12. Config-authority validation after additional llm-area pruning: `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0`
13. Runtime compaction regression slice: `pytest tests/test_context_sync_policy.py` -> `7 passed`; `pytest tests/test_memory_compaction.py tests/test_memory_spine_sqlite.py tests/test_cognitive_learner.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_tuneables_alignment.py` -> `93 passed`
14. Advisory decoupling regression slice: `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_engine_evidence.py tests/test_advisory_engine_on_pre_tool.py tests/test_advisory_orchestrator.py tests/test_advisory_dual_path_router.py tests/test_context_sync_policy.py` -> `41 passed`; `python -m py_compile ...` pass
15. Retrieval/readiness regression slice: `pytest tests/test_advisory_packet_store.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_tuneables_alignment.py` -> `19 passed`; `pytest tests/test_advisor.py tests/test_advisor_retrieval_routing.py` -> `116 passed`
16. Retrieval miss-path regression slice: `pytest tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py` -> `130 passed`; `python -m py_compile lib/advisory_packet_store.py tests/test_advisory_packet_store.py` -> pass
17. Config/packet-store cleanup regression slice: `pytest tests/test_advisory_packet_store.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py` -> `32 passed`; `python -m py_compile lib/advisory_packet_store.py` -> pass
18. SQLite packet-spine integration slice: `python -m lib.tuneables_schema` -> `ok=True`, `unknown=0`; `pytest tests/test_advisory_packet_store.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py` -> `155 passed`; `python -m py_compile lib/advisory_packet_spine.py lib/advisory_packet_store.py` -> pass
19. Post-legacy-test deletion advisory slice: `pytest tests/test_advisory_engine_alpha.py tests/test_advisory_orchestrator.py tests/test_advisory_engine_evidence.py tests/test_advisory_engine_lineage.py tests/test_advisory_packet_store.py tests/test_advisor.py tests/test_advisor_retrieval_routing.py tests/test_tuneables_alignment.py tests/test_pr1_config_authority.py` -> `171 passed`
20. Controlled-delta alpha-route smoke: `python -m py_compile scripts/advisory_controlled_delta.py` -> pass; `python scripts/advisory_controlled_delta.py --rounds 2 --label smoke_alpha --out benchmarks/out/advisory_delta_smoke_alpha.json` -> pass
21. Replay alignment slice: `python -m py_compile scripts/spark_alpha_replay_arena.py scripts/run_alpha_replay_evidence.py` -> pass; `pytest tests/test_spark_alpha_replay_arena.py tests/test_run_alpha_replay_evidence_helpers.py` -> `6 passed`; replay smoke run (`--episodes 8 --seed 42`) passed

## Gap vs V2 Simplification Scope
1. Storage consolidation (128 files -> single spine): partial (cognitive SQLite-canonical + advisory packet SQLite spine integrated; JSON compatibility/fallback still present)
2. Unified noise classifier: done (shadowed, enforce-capable)
3. Advisory collapse (17 files -> 3): partial
4. Memory compaction (ACT-R + Mem0 protocol): partial
5. Delivery-time retrieval improvement: partial
6. VibeForge self-improvement loop (goal + oracle + propose/test/promote ledger): partial
7. Config reduction (576 -> ~70): pending
8. Distillation pipeline collapse: pending
9. Test overhaul (behavioral/replay dominant): partial (legacy dual-path advisory test suites removed; broader mock-heavy surface pruning remains)
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
6. Added JSON consumer inventory tooling (`scripts/memory_json_consumer_audit.py`) and streak gate (`scripts/memory_json_consumer_gate.py`) for explicit retirement readiness.
7. Added ACT-R style compaction planner (`lib/memory_compaction.py`) and preview/apply runner (`scripts/cognitive_memory_compaction.py`) with Mem0 action labels.
8. Added bounded periodic ACT-R compaction in runtime context sync with explicit deletion caps.
9. Remaining: optional removal of non-canonical/legacy compatibility lanes after full JSON deprecation sign-off; runtime path is already SQLite-only.

### PR-05 Retrieval Fusion (RRF + Contextual Retrieval)  (Done for Current Scope)
1. Hybrid retrieval now includes deterministic RRF fusion (semantic + lexical + support ranks).
2. Improve dominant-key and low-sim behavior.
3. Added packet freshness extension on usage to reduce stale-store decay for active advisory packets.
4. Added semantic-only cognitive advisory path and removed legacy keyword fallback branch.
5. Removed superseded fallback rank-extension branch in prefilter ranking path.
6. Removed legacy advisory parser fallback branches (markdown/engine preview).
7. Collapsed per-profile/per-domain weight branching to one deterministic fusion-weight baseline while keeping explicit overrides.
8. Remaining: broader retrieval simplification and post-cutover deletion pass outside these branches.

### PR-06 Advisory Alpha Vertical Slice  (Near Complete)
1. Emission reliability and trace binding improved.
2. Added compact `advisory_engine_alpha` pre-tool path (retrieve -> gate -> synthesize -> emit).
3. Added route orchestrator for pre/post/prompt flows with canary routing and fallback.
4. Route default is now `alpha`; automatic alpha->engine fallback in orchestrator is removed.
5. Startup runtime default is now `alpha` (canary/engine remain explicit opt-in routes).
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
10. Added benchmark-stage blocking checks (`goal.benchmark_checks[]`) evaluated only after cheap gate pass; failing checks auto-rollback promotion candidates.
11. Remaining: EVOLVE-BLOCK code patch lane and richer multi-stage benchmark/oracle policy beyond current blocking checks.

### PR-09 Config Reduction + Utility Dedup  (Partial)
1. Consolidated duplicated JSONL helpers into shared `lib/jsonl_utils.py`.
2. Replaced local helper copies in advisory engine/orchestrator/alpha/quarantine modules.
3. Removed dead advisory fallback tuneables (`fallback_budget_cap/window`) from schema after fallback lane deletion.
4. Removed stale fallback-budget keys from baseline config (`config/tuneables.json`) and aligned docs/observatory references.
5. Added missing `workflow_evidence` schema/config-authority integration to eliminate unknown config surface.
6. Removed unused `dedupe_optimize` llm-area config surface from dispatch/schema/baseline config.
7. Removed unused `suppression_triage` llm-area surface from advisory runtime + dispatch/schema/baseline config.
8. Remaining: broad tuneable pruning and additional utility dedup across non-advisory surfaces.

### PR-10 Legacy Deletion Sweep (Mandatory)  (Partial)
1. Removed hook-level legacy fallback (`observe.py` direct `advisor.advise_on_tool` fallback).
2. Removed legacy `live_quick` fallback route from advisory engine.
3. Removed packet no-emit fallback emission path; gate suppression now stays explicit no-emit.
4. Removed dead fallback control surface (unused fallback env/tuneable plumbing + dead helper functions).
5. Removed orchestrator automatic alpha->engine fallback path (engine now explicit-route only).
6. Removed advisory-emitter legacy compatibility shim (`_emit_advisory_compat`) from advisory engine hot path.
7. Removed duplicate route-only ledger field (`route_hint`) from advisory decision entries.
8. Removed route-derived `provider_path` diagnostics field from advisory engine envelope.
9. Made live advisory orchestration alpha-only (legacy/canary runtime branches removed from orchestrator hot path).
10. Collapsed standalone post-gate text-signature dedupe into the existing emission-quality filter (single suppression pass).
11. Removed dead route-only diagnostics parameter threading from advisory engine diagnostics envelope/callers.
12. Removed dead global dedupe helper functions superseded by preloaded dedupe snapshot + quality filter path.
13. Removed LLM-assisted dedupe-scope optimizer from runtime and made global scope deterministic.
14. Remaining: larger advisory-stack file deletion set after live canary pass.
15. Pending broader sweep once PR-03/04/05/06 are proven:
   - Legacy advisory stack (targeting 17-file collapse from V2)
   - Redundant noise filters no longer used
   - Legacy storage write paths replaced by SQLite spine
16. Output required: explicit deleted file list + LOC removed + rollback tag.

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
