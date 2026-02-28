# Spark V2 FastTrack Implementation Plan

**Date**: 2026-02-26  
**Status**: Execution-ready  
**Timeline**: 21 days (2026-02-27 to 2026-03-19)  
**Objective**: Ship a better Spark now by combining Carmack-style subtraction with a compact, evidence-gated self-improving loop.

---

## 1) Product Outcome

Ship a visibly better advisory loop in 7 days, then complete architecture replacement in parallel without quality regression:

- Less repetitive advice.
- More context-specific advice.
- Stable runtime.
- Daily measurable improvement via controlled policy updates.

This plan replaces long serial phases with **parallel lanes + hard gates**.

---

## 2) Operating Constraints (Non-Negotiable)

1. No big-bang rewrites.
2. No deletion before parity evidence.
3. One canonical metric definition per KPI.
4. One change per nightly self-improvement cycle.
5. Every promotion must pass replay gate + canary gate.
6. If a gate fails, auto-rollback.

---

## 3) Locked Baseline (As Of 2026-02-26)

From current runtime reports:

- Retrieval guardrails failing on:
  - `capture.noise_like_ratio = 0.311` (target `<= 0.15`)
  - `context.p50 = 53` (target `>= 120`)
  - Source: [2026-02-26_memory_quality_observatory.md](/C:/Users/USER/Desktop/vibeship-spark-intelligence/docs/reports/2026-02-26_memory_quality_observatory.md)
- Cross-surface drift incidents: `2`
  - Source: [2026-02-26_cross_surface_drift.md](/C:/Users/USER/Desktop/vibeship-spark-intelligence/docs/reports/2026-02-26_cross_surface_drift.md)
- Production loop gates: `13/19` pass, `NOT READY`
  - Key failures: strict trace coverage, strict acted-on rate, advisory freshness/readiness, meta quality band.
- Advisory repetition concentration: top repeated advice share ~`43.7%`
  - Source: [2026-02-26_135314_advisory_self_review.md](/C:/Users/USER/Desktop/vibeship-spark-intelligence/docs/reports/2026-02-26_135314_advisory_self_review.md)

These are the baseline values for all improvement claims.

---

## 4) Execution Model (Parallel Lanes)

## Lane A: Ship-Now Quality (user-visible in 7 days)

Focus:
- Repeat/suppression control.
- Capture noise reduction.
- Context quality increase.
- Relevance boost for emitted advice.

## Lane B: Core Simplification (no pause between phases)

Focus:
- Active-state SQLite backbone.
- Unified noise classifier.
- Advisory runtime collapse behind a compatibility facade.
- Controlled cutover via dual-run.

## Lane C: Self-Improving Loop (compact and gated)

Focus:
- Nightly one-delta policy cycle.
- Replay + canary + rollback.
- Small action space (8-12 knobs max).

All lanes run together with shared gates.

---

## 5) 21-Day Calendar

## Week 1 (2026-02-27 to 2026-03-05): Ship Better Product Now

### Day 1-2 (Feb 27-28): Metric Contract and Baseline Freeze

Implementation:
1. Freeze canonical KPI definitions in one place (emit rate, noise ratio, context p50, strict attribution, repeat share).
2. Align Observatory/Pulse/report generators to the same formulas.
3. Start day trial:
   - `python scripts/advisory_day_trial.py start --trial-id fasttrack_w1 --duration-h 72`

Done when:
1. Drift incidents `<= 1/day`.
2. Baseline JSON + markdown report written and versioned.

Rollback:
1. Revert metric-contract PR only (no runtime behavior changes).

### Day 3-4 (Mar 1-2): Capture and Context Hygiene Patch

Implementation:
1. Remove top repeated low-signal capture patterns.
2. Enforce context payload floor before persistence.
3. Increase penalties for known scaffolding/noise classes.

Primary files:
- `hooks/observe.py`
- `lib/memory_capture.py`
- `lib/meta_ralph.py`
- `lib/cognitive_learner.py`

Done when:
1. `capture.noise_like_ratio <= 0.25` (step target).
2. `context.p50 >= 70` (step target).

Rollback:
1. Revert only capture filters and thresholds.

### Day 5-6 (Mar 3-4): Advisory Repeat and Dedupe Overreach Patch

Implementation:
1. Reduce global dedupe overreach by category/context-aware windows.
2. Add explicit repeated-advice suppression for identical low-value outputs.
3. Keep strict safeguards on safety/security advisories.

Primary files:
- `lib/advisory_engine.py`
- `lib/advisory_gate.py`
- `lib/advisory_packet_store.py`

Canary:
- Run 12h canary on cooldown and repeat controls.
- `python scripts/advisory_day_trial.py snapshot --trial-id fasttrack_w1 --run-canary --timeout-s 1800`

Done when:
1. Emit rate improves without unhelpful spike.
2. Repeated advice concentration drops materially from baseline.

Rollback:
1. Revert dedupe/cooldown patch; keep capture improvements.

### Day 7 (Mar 5): Week-1 Ship Gate

Close trial:
- `python scripts/advisory_day_trial.py close --trial-id fasttrack_w1 --timeout-s 1800`

Ship gate:
1. No critical regressions in canary.
2. User-visible quality improved on repetition and specificity.
3. Runtime health stable.

---

## Week 2 (2026-03-06 to 2026-03-12): Architecture Replacement in Parallel

### Batch B1: Active-State SQLite Backbone (Dual-Write)

Implementation:
1. Add `lib/spark_db.py` (connection, migrations, typed CRUD).
2. Add active tables: events, insights, advisory_decisions, feedback, state.
3. Wire dual-write from current JSONL + SQLite for active path.
4. Keep archive/history outside scope this week.

Primary files:
- `lib/spark_db.py` (new)
- `hooks/observe.py`
- `lib/bridge_cycle.py`
- `lib/cognitive_learner.py`
- `lib/advisory_engine.py`

Done when:
1. Active read parity confirmed on replay.
2. No data-loss and no latency breach.

Rollback:
1. Disable dual-write flag and keep JSONL canonical.

### Batch B2: Unified Noise Classifier (Single Source)

Implementation:
1. Add `lib/noise_classifier.py`.
2. Replace local pattern implementations with shared `classify()` calls.
3. Keep decision reason tags for observability.

Primary files:
- `lib/noise_classifier.py` (new)
- `lib/meta_ralph.py`
- `lib/cognitive_learner.py`
- `lib/promoter.py`
- `lib/primitive_filter.py` and `lib/noise_patterns.py` (deprecate)

Done when:
1. Noise precision/recall passes replay thresholds.
2. No increase in false-negative capture of high-signal insights.

Rollback:
1. Switch call sites back to local filters.

### Batch B3: Advisory Facade for Collapse Without Big-Bang

Implementation:
1. Introduce thin facade API (`retrieve -> rank -> gate -> emit`) with adapters to old internals.
2. Move complex side subsystems (prefetch/opportunity-like paths) off hot path.
3. Dual-run facade vs legacy in shadow mode.

Primary files:
- `lib/advisory_engine.py`
- `lib/advisor.py`
- `lib/advisory_gate.py`
- `lib/advisory_packet_store.py`

Done when:
1. Shadow parity on selected routes.
2. Facade route can serve production path under flag.

Rollback:
1. Route back to legacy path.

---

## Week 3 (2026-03-13 to 2026-03-19): Compact Self-Improving Loop

### Batch C1: Nightly Policy Loop (One Delta Per Cycle)

Implementation:
1. Restrict optimizer action space to max 12 policy knobs.
2. For each nightly cycle:
   - propose one delta
   - run replay eval
   - run canary
   - promote or rollback
3. Log each cycle in a policy ledger with evidence links.

Primary files:
- `scripts/run_advisory_retrieval_canary.py`
- `scripts/advisory_day_trial.py`
- `lib/production_gates.py`
- `lib/auto_tuner.py` (or replacement orchestrator)

Done when:
1. Three consecutive non-regressive promoted cycles.
2. Every promoted change has linked replay and canary evidence.

Rollback:
1. Restore tuneables backup from the same cycle.

### Batch C2: Memory Improvement (Only High-ROI Additions)

Implementation:
1. Write-time contextual enrichment for memory entries.
2. ADD/UPDATE/DELETE/NOOP memory update protocol.
3. Basic contradiction/poisoning checks before memory promotion.

Primary files:
- `lib/cognitive_learner.py`
- `lib/memory_store.py`
- `lib/memory_capture.py`
- `lib/advisory_memory_fusion.py`

Done when:
1. Retrieval quality improves on holdout with no safety regression.
2. Duplicate/stale memory rates trend down.

Rollback:
1. Disable update protocol and keep append-only path.

---

## 6) Cutover Strategy (No Dead Time Between Phases)

1. Use **route flags** and **dual-run** to overlap batches.
2. Promote in slices:
   - Slice 1: capture + dedupe improvements (Week 1 ship)
   - Slice 2: SQLite dual-write + unified noise (Week 2)
   - Slice 3: advisory facade primary route (Week 2/3)
   - Slice 4: nightly policy loop (Week 3)
3. Deletions happen only after 2 stable windows:
   - replay pass
   - live canary pass

---

## 7) Runtime Commands (Operator Runbook)

Daily health:
1. `python scripts/status_local.py`
2. `python scripts/production_loop_report.py`
3. `python scripts/memory_quality_observatory.py`
4. `python scripts/carmack_kpi_scorecard.py --window-hours 24 --alert-json`
5. `python scripts/generate_observatory.py --force --verbose`

Trial lifecycle:
1. Start: `python scripts/advisory_day_trial.py start --trial-id <id> --duration-h 72`
2. Snapshot: `python scripts/advisory_day_trial.py snapshot --trial-id <id> --run-canary --timeout-s 1800`
3. Close: `python scripts/advisory_day_trial.py close --trial-id <id> --timeout-s 1800`

Canary:
1. `python scripts/run_advisory_retrieval_canary.py --timeout-s 1800`

Note:
- `production_loop_report.py` returns non-zero when gates fail; this is expected during iteration.

---

## 8) Release Gates

## Gate G1: Week-1 Product Ship

Required:
1. Repetition visibly down.
2. Unhelpful trend not worse.
3. Runtime stable.

## Gate G2: Architecture Cutover

Required:
1. Shadow parity in advisory path.
2. No data-loss under dual-write.
3. Guardrails not worse than baseline.

## Gate G3: Self-Improving Loop Promotion

Required:
1. Policy change passes replay + canary.
2. Regression auto-rollback proven.
3. Evidence ledger complete.

---

## 9) Explicit Defer List (Do Not Build In This Window)

1. Multi-hop memory graph traversal.
2. Broad autonomous code rewriting by learner.
3. Additional control planes or new daemon families.
4. New platform abstractions not required by active gates.

---

## 10) Definition of Success (2026-03-19)

1. Spark ships a clearly better advisory experience than 2026-02-26 baseline.
2. Core runtime path is simpler and traceable end-to-end.
3. Self-improvement loop is real, compact, reversible, and evidence-gated.
4. Team can improve quality weekly without architecture churn.

