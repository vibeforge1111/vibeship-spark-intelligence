# Spark Alpha Rebuild Plan

Date: 2026-02-26
Branch: feat/simplification-hard-reset
Status: execution blueprint

## 1) Objective

Ship a real alpha loop, not a patched loop:

- reliable memory intake
- useful advisory emission
- explicit self-improving policy cycle
- simpler architecture with fewer hidden states

This plan intentionally takes bigger risks on a branch, then does a decisive cutover only if evidence is clear.

## 2) Why This Plan Is Different

Current failures are concentrated in three coupled layers:

1. distillation complexity without yield
2. meta-quality gating that blocks throughput
3. advisory path that emits too little and learns weakly

So the plan is not incremental tuning. It is a branch-first rebuild of the core loop with shadow evidence and a defined cutover gate.

## 3) Keep vs Replace

Keep now:

1. hook ingestion entry points (`hooks/observe.py`)
2. queue and bridge scheduling shell (temporarily)
3. strict trace lineage fields and outcome logging pattern
4. production gate and observability command surface

Replace aggressively:

1. multi-implementation noise filtering -> one classifier
2. current meta-ralph scoring path -> simpler scorer + safety checks
3. fragmented advisory internals -> single hot path (`retrieve -> rank -> gate -> emit`)
4. fragmented active state files -> SQLite active-state spine

Defer until alpha is alive:

1. advanced memory graph traversal
2. broad cross-domain transfer logic
3. massive config purge
4. large test deletions

## 4) Target Alpha Architecture

Minimal runtime spine:

1. `observe`: ingest events
2. `noise_classifier`: reject garbage
3. `scorer`: score candidate learning
4. `memory_store` (SQLite): persist active memories/outcomes
5. `advisory_engine_alpha`: retrieve/rank/gate/emit
6. `policy_loop`: one bounded change per cycle with replay and canary

Legacy modules stay available behind flags for rollback until cutover.

## 5) High-Risk Bets (Intentional)

These are the bets that can materially change product quality:

1. Replace Meta-Ralph gating on hot path with a simpler score pipeline in shadow-then-primary mode.
2. Replace advisory orchestration on hot path with a compressed vertical slice.
3. Move active loop state to SQLite dual-write then SQLite-primary.

Each bet requires:

1. feature flag default-off
2. side-by-side telemetry (`legacy` vs `alpha`)
3. auto-rollback trigger

## 6) Execution Program (4 Waves)

## Wave 0 (Day 0): Baseline Rehydrate + Contract Lock

1. Rehydrate a realistic local baseline from available archives into active stores.
2. Lock canonical metric formulas and report contract version.
3. Freeze baseline snapshot for comparison.

Exit criteria:

1. non-zero capture and cognitive baseline
2. comparable 24h metric baseline artifact generated

## Wave 1 (Day 1-2): Intake and Scoring Reset

1. implement single noise classifier and wire shadow comparisons in all call sites
2. add simple scorer and run dual-score mode beside legacy scoring
3. add loop-alive counters:
   - candidate_count
   - accepted_count
   - emitted_count
   - trace_bound_count

Exit criteria:

1. disagreement report generated
2. accepted_count recovers without safety spike

## Wave 2 (Day 3-4): Advisory Alpha Hot Path

1. implement `advisory_engine_alpha` with:
   - retrieve
   - rank
   - gate
   - emit
2. route small traffic slice to alpha path on branch canary runs
3. compare:
   - emission rate
   - follow/helpful trend
   - unhelpful/harmful trend
   - trace coverage

Exit criteria:

1. alpha emission materially higher than legacy
2. no quality collapse on negative signals

## Wave 3 (Day 5-6): SQLite Active-State Spine

1. introduce unified active-state SQLite schema
2. dual-write events/insights/advisory decisions/outcomes
3. run read-shadow parity reports

Exit criteria:

1. parity above threshold
2. no data-loss incidents

## Wave 4 (Day 7): Cutover Decision

Decision is binary:

1. CUTOVER if alpha beats legacy on core metrics for 48h equivalent replay/canary evidence
2. NO CUTOVER if evidence is mixed; keep best subsystems and continue branch iteration

## 7) Hard Gates for Cutover

All must pass:

1. advisory emit rate improves by >= +5pp from baseline
2. strict trace coverage >= 50%
3. retrieval guardrail failures do not increase
4. context p50 >= 80 as first alpha floor
5. no critical regression in unhelpful/harmful indicators
6. SQLite parity within defined tolerance for dual-write metrics

## 8) Rollback Rules

Immediate rollback of changed route if any trigger persists across two checkpoints:

1. emitted_count drops to near-zero
2. strict trace coverage drops by >10pp
3. harmful/unhelpful signals spike materially
4. parity drift breaches tolerance

Rollback method:

1. flip route flag to legacy
2. keep telemetry for root cause
3. patch and re-canary

## 9) What We Build First (Exact Priority)

Priority order for implementation:

1. baseline rehydrate + metric contract lock
2. unified noise classifier
3. simple scorer dual mode
4. advisory alpha hot path
5. SQLite dual-write and parity
6. one-delta policy loop
7. post-cutover deletions

## 10) Definition of Alpha Success

Spark alpha is achieved when:

1. the loop is alive (continuous memory intake + non-trivial emissions)
2. advisory usefulness improves with evidence, not anecdotes
3. the self-improvement cycle can safely promote or rollback changes
4. the runtime is simpler to reason about than current state

