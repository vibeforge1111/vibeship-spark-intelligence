# Spark Alpha SOTA Implementation Plan

Date: 2026-02-28
Scope: Spark Intelligence alpha -> SOTA intelligence layer (beyond memory) with safe self-evolution
Status: Execution-ready plan based on live runtime + test baseline + architecture review

## Execution Update (2026-02-28)

- Completed: `P0-A` Observatory advisory decision fallback + source/freshness labeling (explorer + reverse engineering surfaces).
- Completed: `P0-B` tuneables observability fallback to config-authority/versioned snapshot when `~/.spark/tuneables.json` is absent.
- Completed: `P0-C` provider fidelity release gating in preflight:
  - active provider breach budget now blocks release when breaches persist for `>=2` windows,
  - unavailable providers are surfaced separately without being conflated with active degraded providers.
- Completed: `P0-E` preflight hygiene visibility:
  - shadow log cap check (`noise_classifier_shadow.jsonl`) with tolerance,
  - memory WAL budget check (`spark_memory_spine.db-wal`).
- Completed: `P0-D` red-test closure (baseline 7/7 fixed):
  - cognitive persistence compatibility path restored (`cognitive_insights.json` + legacy mirror),
  - bridge contextual retrieval reserve behavior corrected for reasoning-heavy insights,
  - noise filtering enforcement now preserves legacy catch-all for known noise cases,
  - Meta-Ralph primitive/scoring dual-lane corrected (alpha primary with legacy shadow safety merge).

Current release state (live check on 2026-02-28):
- `alpha_preflight_bundle`: `ready=false` due to repeated Claude `tool_result_capture_rate` breach.
- `production_gates`: still passing (`19/19`), indicating quality gates pass while cross-provider fidelity remains the active blocker.
- Full tests: `1458 passed, 3 skipped` (`pytest -q`, 2026-02-28).

## 1) Baseline (as of 2026-02-28)

### Live checks run
- `python scripts/production_loop_report.py --json`: `READY (19/19 passed)`
- `python scripts/alpha_preflight_bundle.py --json-only`: `ready=true`
- `python scripts/codex_hooks_observatory.py --json-only`: required gates passing
- `python scripts/workflow_fidelity_observatory.py --json-only`:
  - `claude` tool-result capture rate: `0.0299` (critical breach vs `>=0.65`)
  - `codex` truncation ratio: `1.0` (warning vs `<=0.8`)
  - `openclaw`: unavailable
- Local runtime artifacts:
  - `~/.spark/advisory_decision_ledger.jsonl`: missing
  - `~/.spark/tuneables.json`: missing

### Test baseline run
- `pytest -q` result: `7 failed, 1445 passed, 3 skipped`
- Failing tests:
  - `tests/test_10_improvements.py::test_2_persistence_pipeline`
  - `tests/test_bridge_context_sources.py::test_contextual_insights_reserve_mind_slot`
  - `tests/test_cognitive_noise_filter.py::test_noise_filter_rejects_rambling_when_using_remember_transcript`
  - `tests/test_cognitive_noise_filter.py::test_noise_filter_rejects_indented_code_snippet`
  - `tests/test_meta_ralph.py::test_quality_detection`
  - `tests/test_meta_ralph.py::test_scoring_dimensions`
  - `tests/test_metaralph_integration.py::test_storage_layer`

### Key contradiction resolved
- Advisory is not globally offline. `advisory_engine_alpha` logs and reverse-engineering page show active emissions.
- But some Observatory surfaces remain ledger-only (for example `explore/decisions/_index.md`), causing `0/0` false-red when ledger is missing.

## 2) Decision

Ship posture remains `Limited Alpha` until P0 is complete.
Do not claim full SOTA layer or safe self-evolution until:
- telemetry truth contract is enforced,
- provider fidelity gate includes Claude/OpenClaw parity,
- 0 failing tests in baseline suite,
- memory + advisory guardrails pass continuously.

## 3) Priority Roadmap

## P0 (Days 0-14): Truth, Safety, and Release Integrity

### P0-A. Observatory metric source integrity
Owner: Observability Engineer
Dependencies: none

Implement:
- Add metric source labeling + confidence everywhere advisory/tuneables metrics are shown.
- Extend ledger fallback beyond stage readers into explorer views:
  - `lib/observatory/explorer.py` (`_export_decisions`) should fallback to `advisory_engine_alpha` then `advisory_emit`.
- Update `lib/observatory/advisory_reverse_engineering.py`:
  - display `ledger_source`,
  - rename displayed metric from "Ledger rows" to "Decision rows",
  - show freshness timestamp per source.

Acceptance metrics:
- `decision_source` shown on all advisory decision pages.
- No advisory page reports `emit_rate=0.0% (0/0)` when `advisory_engine_alpha` has decision events in window.
- Source-integrity test coverage added for explorer and reverse-engineering.

Rollback:
- Keep current renderers behind feature toggle if page generation regresses.

### P0-B. Tuneables observability integrity (runtime file optional)
Owner: Config/Platform Engineer
Dependencies: P0-A

Implement:
- Replace direct `~/.spark/tuneables.json` assumptions in observability paths with config-authority-resolved view.
- In `lib/observatory/tuneables_deep_dive.py` and advisory reverse-engineering tuneables snapshot:
  - source modes: `runtime`, `versioned`, `resolved`,
  - confidence label and drift interpretation tied to source mode.
- Treat missing runtime tuneables as `degraded visibility`, not automatic config drift failure.

Acceptance metrics:
- Tuneables deep dive does not report full-section false drift when runtime file is absent.
- Page explicitly states which source is authoritative.
- New tests cover missing-runtime-file path.

### P0-C. Provider fidelity hard gate in release path
Owner: Runtime Integration Engineer
Dependencies: P0-A

Implement:
- Integrate `workflow_fidelity_observatory` checks into:
  - `scripts/alpha_preflight_bundle.py`
  - CI workflow (`.github/workflows/ci.yml`)
- Gate by provider:
  - `tool_result_capture_rate >= 0.65`
  - `truncated_tool_result_ratio <= 0.80`
  - stale window failure handling
- Add separate policy for unavailable providers (`openclaw`) vs degraded active providers (`claude`).

Acceptance metrics:
- Preflight output includes per-provider pass/fail.
- CI blocks release when active provider is below threshold for 2+ windows.

### P0-D. Red test closure (7/7)
Owner: QA + Module Owners
Dependencies: none

Fix clusters:
- Persistence/storage tests:
  - align integration tests with SQLite-canonical memory spine (not JSON-only assumptions).
- Contextual retrieval sloting:
  - fix `CONTEXT_MIND_RESERVED_SLOTS` behavior in `lib/bridge.py`.
- Noise filter regressions:
  - align `CognitiveLearner.is_noise_insight()` with expected transcript/code-noise patterns.
- Meta-Ralph quality/reasoning regressions:
  - adjust primitive/reasoning scoring to satisfy quality and dimension tests.

Acceptance metric:
- `pytest -q` green (`0 failed`).

### P0-E. Runtime hygiene guardrails
Owner: Runtime Ops
Dependencies: none

Implement:
- enforce JSONL cap rotation for shadow logs,
- WAL checkpoint routine for memory spine DB,
- add hygiene checks to daily scheduler and observatory.

Acceptance metrics:
- No file exceeds configured cap by >5% for 24h.
- WAL stays below agreed ceiling (for example 1 MB steady-state target).

## P1 (Days 15-45): Quality Lift + Controlled Intelligence Amplification

### P1-A. Advisory efficacy experiment loop
Owner: Advisory Lead
Dependencies: P0-A/B/C/D

Execution loop:
- `scripts/verify_advisory_emissions.py`
- `scripts/run_advisory_realism_domain_matrix.py`
- `scripts/spark_alpha_replay_arena.py`
- `scripts/run_advisory_retrieval_canary.py`

Targets:
- harmful emit rate <= 0.02
- critical miss rate <= 0.10
- trace-bound rate >= 0.80
- winner score trend increasing over 3 consecutive runs

### P1-B. Memory retrieval quality hardening
Owner: Retrieval Lead
Dependencies: P0-D

Execution loop:
- `scripts/build_multidomain_memory_retrieval_cases.py`
- `scripts/semantic_eval.py`
- `scripts/memory_quality_observatory.py`

Targets (metric contract aligned):
- `semantic.sim_avg >= 0.22`
- `semantic.sim_lt_0_1_ratio <= 0.20`
- `semantic.dominant_key_ratio <= 0.35`
- `capture.noise_like_ratio <= 0.15`
- `context.p50 >= 120`

### P1-C. Meta-Ralph calibration + enforcement
Owner: Learning/Quality Lead
Dependencies: P0-D

Execution loop:
- `scripts/metaralph_calibrate_quality.py`
- plus replay + production gates validation

Targets:
- quality-rate in target band with enforcement enabled after sample floor
- false-reject regression tests added (quality examples that must pass)
- no increase in unsafe pass-through rates

### P1-D. Staged enablement of high-impact LLM areas (top 5)
Owner: AGI Runtime Lead
Dependencies: P1-A/B/C

Phase-in candidates:
- `meta_ralph_remediate`
- `novelty_score`
- `conflict_resolve`
- `generic_demotion`
- `retrieval_rewrite`

Guardrails:
- one area enabled per canary window,
- auto-rollback on any gate failure,
- per-area ablation scorecard required before promotion.

## P2 (Days 46-90): Structural Decoupling + Self-Evolution Control Plane

### P2-A. Monolith extraction tranche 1 then tranche 2
Owner: Architecture Lead
Dependencies: P1 stability

Tranche 1:
- `lib/advisor.py`
- `hooks/observe.py`

Tranche 2:
- `lib/advisory_packet_store.py`
- `lib/bridge_cycle.py`
- `lib/meta_ralph.py`

Success metrics:
- each extracted hotspot < 1500 LOC
- characterization tests unchanged behavior
- no performance regression > 10% on critical paths

### P2-B. Self-evolution loop with hard simulation gate
Owner: AGI Systems Lead
Dependencies: P0-C + P1-A/B/C

Use existing framework:
- `scripts/vibeforge.py` for proposal lanes
- `scripts/spark_alpha_replay_arena.py` for simulation
- production gates + fidelity + memory guardrails as ship criteria

Policy:
- allow autonomous changes only in evolve-allowed surfaces initially (tuneables-first),
- require champion/challenger replay win + gate pass before apply,
- rollback snapshot mandatory.

Success metrics:
- 100% of automated proposals have reproducible simulation artifact
- 0 ungated autonomous production mutations
- regret trend non-increasing over consecutive cycles

## 4) Obsidian Observatory Expansion (implementation)

Add pages (generated by `scripts/alpha_observatory_expand.py` extension):
- `_observatory/metric_source_integrity.md`
- `_observatory/provider_fidelity_matrix.md`
- `_observatory/advisory_data_contract.md`
- `_observatory/runtime_config_integrity.md`
- `_observatory/spaghetti_heatmap.md`

Minimum schema per key metric:
- `metric_id`
- `value`
- `source_path`
- `source_mode` (`runtime|versioned|resolved|fallback`)
- `freshness_s`
- `confidence` (`high|medium|low`)
- `fallback_used` (bool)
- `last_validated_at`

Ship gate:
- release blocked if any P0 metric is `source_mode=unknown` or freshness exceeds SLO.

## 5) Benchmark and Test Operating Cadence

### Per commit / PR
- `pytest -q`
- `python scripts/production_loop_report.py --json`
- `python scripts/codex_hooks_observatory.py --json-only`
- `python scripts/workflow_fidelity_observatory.py --json-only`

### Daily
- `python scripts/memory_quality_observatory.py`
- `python scripts/generate_observatory.py --force --verbose`
- `python scripts/alpha_observatory_expand.py`

### Weekly
- `python scripts/run_advisory_realism_domain_matrix.py`
- `python scripts/run_advisory_retrieval_canary.py`
- `python scripts/spark_alpha_replay_arena.py`
- `python scripts/openclaw_realtime_e2e_benchmark.py`
- `python scripts/run_indirect_intelligence_flow_matrix.py`

## 6) Risks and Mitigations

- Risk: advisory telemetry still disagrees across pages.
  - Mitigation: single decision contract + source labels + reconciliation check.
- Risk: enabling LLM areas increases variance/hallucination.
  - Mitigation: one-by-one canary with rollback and ablation scorecards.
- Risk: monolith extraction causes hidden behavior drift.
  - Mitigation: characterization tests + replay arena before merge.
- Risk: provider parity blocks release velocity.
  - Mitigation: explicit degraded-provider policy and separate ship classes.

## 7) Definition of Complete (SOTA layer claim gate)

Spark can be labeled a SOTA intelligence layer only when all are true:
- telemetry truth contract passes continuously for 14 days,
- provider fidelity gates pass for active providers,
- baseline test suite has 0 failures,
- memory/advisory retrieval guardrails pass continuously for 14 days,
- advisory quality benchmarks show stable uplift and low harmful-emit rate,
- self-evolution changes are simulation-gated, auditable, and rollback-safe.

Until then: classify as `Limited Alpha`.

## 8) Research Anchors Used

- Knowledge distillation: Hinton et al., 2015
  - https://arxiv.org/abs/1503.02531
- Retrieval-augmented generation: Lewis et al., 2020
  - https://arxiv.org/abs/2005.11401
- Retrieval benchmarking (OOD robustness): BEIR, 2021
  - https://arxiv.org/abs/2104.08663
- RAG evaluation framework: RAGAS, 2023
  - https://arxiv.org/abs/2309.15217
- Contextual bandits + offline evaluation: Li et al., 2010
  - https://arxiv.org/abs/1003.0146
- Calibration for confidence-based gating: Guo et al., 2017
  - https://arxiv.org/abs/1706.04599
- Selective classification / abstention gating: Geifman and El-Yaniv, 2017
  - https://arxiv.org/abs/1705.08500
- Canary release process and gating: Google SRE Workbook
  - https://sre.google/workbook/canarying-releases/
