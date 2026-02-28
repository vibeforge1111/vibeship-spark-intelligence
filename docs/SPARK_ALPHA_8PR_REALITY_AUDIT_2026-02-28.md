# Spark Alpha Reality Audit (8PR + Rebuild Plan)

Date: 2026-02-28
Branch: feat/spark-alpha
Scope: Planned vs live-runtime validation against `docs/SPARK_ALPHA_8PR_EXECUTION_PLAN.md` and `docs/SPARK_ALPHA_REBUILD_PLAN.md`.

## Executive Verdict

- Alpha core runtime is live and healthy: `alpha_preflight_bundle` is green (`ready=true`) and production gates are `19/19` passing.
- PR-01/02/04/06/07 are materially implemented and active in runtime.
- PR-03 is implemented but diverged from the original dual-score operating model (alpha-primary + legacy fallback, not active dual adjudication).
- PR-05 is active but not fully realized by quality bar: overall gate passes, but retrieval quality is uneven by domain and route telemetry has large unknown/empty slices.
- PR-08 (daily governor) exists as tooling (`vibeforge`) but is not operationalized in runtime orchestration.
- Advisory 4-hour review system is present and running; report center/index in Obsidian exists and is linked.
- External LLM rating in usefulness cycle is currently unreliable (`claude parsed_ratings=0` in latest run), causing heavy heuristic-only labeling.
- Biggest remaining alpha risk is not infra uptime; it is intelligence-quality calibration and self-improvement governance.

## Evidence Snapshot

- `python scripts/alpha_preflight_bundle.py --json-only` -> `ready=true`
- `python scripts/check_pr5_readiness.py` -> `pass=true`, `overall_precision_at_5=0.376`, `p95_latency_ms=505.2`, `research.avg_precision=0.0`
- `python scripts/memory_spine_parity_report.py` -> payload parity `1.0`
- `python scripts/memory_json_consumer_gate.py` -> `runtime_hits=0` (streak `1/3`)
- `python scripts/spark_alpha_replay_arena.py --episodes 8 --seed 42 --out-dir benchmarks/out/replay_arena_smoke` -> `winner=alpha`, `promotion_gate_pass=true`, streak `24`
- `python scripts/advisory_usefulness_cycle.py ...` -> `candidate_count=80`, `applied_count=40`, `provider_attempts: claude parsed_ratings=0`

## PR-by-PR Reality Matrix

| PR | Plan Intent | Live Status | Evidence | Gaps / Risk |
|---|---|---|---|---|
| PR-01 | Baseline rehydrate + metric contract lock | Implemented, mostly active | `lib/metric_contract.py`; used in `lib/production_gates.py` and `scripts/cross_surface_drift_checker.py`; `scripts/rehydrate_alpha_baseline.py` exists | Baseline rehydrate/drift checks are not enforced in recurring runtime gate cycle |
| PR-02 | Unified noise classifier (shadow-first) | Implemented, active in core learning/promotion | `lib/noise_classifier.py`; wired in `lib/meta_ralph.py`, `lib/cognitive_learner.py`, `lib/promoter.py` | Ingress capture path (`hooks/observe.py`) does not appear to use unified classifier as first-class stage |
| PR-03 | Meta reset via dual scoring | Partially aligned / diverged | `lib/meta_ralph.py` + `lib/meta_alpha_scorer.py` present; alpha scorer primary with legacy fallback | Original dual adjudication/decision-source comparison is no longer an active runtime mode |
| PR-04 | SQLite memory spine + contextual write + deterministic ops | Implemented, active | `lib/spark_memory_spine.py`; SQLite-canonical path enabled; parity report passes `1.0`; runtime JSON hits `0` | Retirement streak gate not yet complete (`memory_json_consumer_gate` streak `1/3`); deterministic Mem0-style op ledger not yet first-class in hot ingestion loop |
| PR-05 | Retrieval fusion (RRF + contextual RAG + rerank harness) | Active, quality-partial | RRF + rerank in `lib/advisor.py`; harness in `benchmarks/memory_retrieval_ab.py`; PR5 gate script passes | `research` slice precision is `0.0`; route telemetry has many `empty/unknown` entries reducing explainability |
| PR-06 | Advisory alpha vertical slice + strict trace + dedupe | Implemented, runtime primary | `hooks/observe.py` calls `lib/advisory_engine_alpha.py` directly for pre/post/prompt; trace/gate logs active | Alpha hot path still depends on `lib/advisor.py` monolith for retrieval, preserving high coupling risk |
| PR-07 | Deterministic replay arena + promotion ledger | Implemented and functioning | `scripts/spark_alpha_replay_arena.py`, `scripts/run_alpha_replay_evidence.py`; replay smoke passes with streak `24`; ledger exists | Not wired as mandatory periodic runtime governance task (scheduler/CI enforcement still optional/manual) |
| PR-08 | Daily governor (bounded policy loop with replay+canary+rollback) | Tooling present, not operationalized | `scripts/vibeforge.py` provides propose/apply/rollback/ledger flow | No active goal/ledger bootstrapped; not integrated into scheduler; no signed policy ledger; replay+canary not hard-bound in governor promotion flow |

## Rebuild Plan Wave Status

- Wave 0 (Baseline + Contract): done.
- Wave 1 (Intake + Scoring Reset): mostly done, but scorer governance diverged from dual-model plan.
- Wave 2 (Advisory Hot Path): done, with monolith coupling debt still high.
- Wave 3 (SQLite Active-State Spine): mostly done; parity strong, retirement gate streak still pending.
- Wave 4 (Binary cutover): partially evidenced (replay + production gates good), but self-improvement governance (PR-08 operationalization) is incomplete.

## Systems Introduced But Not Fully Effective Yet

1. PR-05 retrieval fusion quality telemetry
- Quality gate passes globally but domain-level quality has blind spots (`research` precision collapse).
- Route telemetry still has high `empty/unknown` mixes, weakening optimization confidence.

2. 4-hour usefulness cycle external adjudication
- Cycle runs and writes ratings, but latest provider attempt failed to return parseable structured ratings (`parsed_ratings=0`).
- This causes heavy heuristic labeling and likely optimistic bias.

3. PR-08 governor (self-evolution)
- Implemented as CLI, but not part of routine runtime control plane.
- Missing always-on operating contract: bootstrap goal, periodic run, replay/canary enforce, signed promotion ledger.

## Prioritized Implementation Plan

### P0 (Next 48 hours)

1. Stabilize usefulness-cycle adjudication quality
- Update `lib/advisory_usefulness_cycle.py` parsing fallback strategy and add strict "no-structured-output" penalty path.
- Prevent mass auto-`helpful` writes when no provider returns valid ratings.
- Gate: `provider_attempts.ok_rate >= 0.7` on rolling 24h, and heuristic-only applied share < 50%.

2. Fix PR-05 telemetry explainability gaps
- Repair route/reason logging completeness in retrieval path (`lib/advisor.py` telemetry writers).
- Gate: `route=empty` and `reason=unknown` each < 5% in 24h windows.

3. Wire replay evidence into recurring ops
- Add scheduler task for replay smoke every 6h and alert on failed promotion gate.
- Gate: no >6h window without replay artifact update; failure triggers explicit alert row.

### P1 (Next 7 days)

1. Reinstate dual-score observability lane (telemetry-only)
- Add sampled legacy-shadow scoring in `meta_ralph` without changing primary decision path.
- Gate: disagreement dashboard with per-pattern drift and zero runtime regression.

2. Promote domain-aware PR-05 gates
- Add per-domain minimum precision checks to PR5 readiness (especially `research`).
- Gate: research precision floor >= 0.20 before promotion.

3. Complete PR-04 retirement streak
- Drive `memory_json_consumer_gate` to required streak and lock runtime JSON retirement in release checklist.

### P2 (Next 2 weeks)

1. Operationalize PR-08 governor
- Bootstrap default forge goal, integrate scheduled cycle, enforce replay+canary pre-promotion checks.
- Add signed/hash-chained policy ledger entries.

2. Reduce PR-06 monolith coupling
- Extract retrieval/ranking/effectiveness submodules from `lib/advisor.py` that are on alpha hot path.
- Gate: behavior-equivalent tests + replay parity pass.

## Definition of "Rest Complete" (for this audit scope)

- PR-05: domain-level quality gates and telemetry completeness are green.
- PR-08: governor is running as an operational service loop, not just a CLI tool.
- Usefulness cycle: provider-based structured ratings are reliable and not overwhelmed by heuristic defaults.
- Replay governance: periodic artifacts + alerting are automatic and visible in Observatory.
