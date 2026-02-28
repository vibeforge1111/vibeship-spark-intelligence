# Spark Alpha: 8-PR Execution Plan (Risk-On, Branch-First)

Date: 2026-02-26
Branch: feat/simplification-hard-reset
Mode: high-risk challenger with hard rollback

## 1) Research Anchors We Are Adopting

Primary-source methods included in this plan:

1. Memory-R1 style learned memory operations (`ADD/UPDATE/DELETE/NOOP`) via RL-trained manager + answer utility rewards.
   - Source: https://arxiv.org/abs/2508.19828
2. Mem-alpha style RL memory construction over long sequences.
   - Source: https://arxiv.org/abs/2509.25911
3. LightMem-inspired lightweight staged memory lifecycle (online fast path + offline consolidation).
   - Source: https://arxiv.org/abs/2510.18866
4. SimpleMem-inspired semantic compression + consolidation + adaptive retrieval.
   - Source: https://arxiv.org/abs/2601.02553
5. Anthropic Contextual Retrieval (contextual chunking + BM25 + rerank) for large retrieval gains.
   - Source: https://www.anthropic.com/research/contextual-retrieval
6. Mem0 production memory update protocol baseline.
   - Source: https://arxiv.org/abs/2504.19413

## 2) Fusion Strategy (What We Keep vs Replace)

Keep:

1. existing hook entry points and scheduler shell
2. strict trace lineage semantics
3. production gate command surface

Replace aggressively:

1. distillation/meta/advisory hot path
2. fragmented active state writes
3. duplicated noise/scoring logic

## 3) 8 PRs to Alpha

## PR-01: Baseline Rehydrate + Metric Contract Lock

Objective:

1. rehydrate realistic baseline from archived stores
2. lock canonical metric formulas and contract version
3. generate baseline evidence snapshot

Deliverables:

1. baseline rehydrate script
2. metric contract module + drift checker
3. baseline report artifacts

Gate:

1. non-zero capture/advisory baseline and reproducible report run

Rollback:

1. disable rehydrate import path and keep read-only contract docs

## PR-02: Unified Noise Classifier (Shadow-First)

Objective:

1. replace 5 noise filters with one classifier API
2. run shadow disagreement logging against legacy logic

Deliverables:

1. `lib/noise_classifier.py`
2. callsite integration in capture/meta/promoter paths
3. disagreement report

Gate:

1. disagreement bounded and no safety-regression spike

Rollback:

1. route all callers back to legacy filter functions

## PR-03: Meta Reset via Dual Scoring

Objective:

1. keep legacy meta path
2. add simple score path (signal-based) in dual mode
3. start reducing false rejects without dropping safety checks

Deliverables:

1. dual-score payload (`legacy_score`, `alpha_score`)
2. score audit dashboard card
3. feature flag for promotion decision source

Gate:

1. accepted_count up while harmful/unhelpful does not spike

Rollback:

1. flip scoring decision to legacy-only

## PR-04: Memory Spine Alpha (SQLite + Contextual Write)

Objective:

1. move active loop state to SQLite dual-write
2. contextual write-time enrichment for memory units
3. Mem0 operations in deterministic mode first (`ADD/UPDATE/DELETE/NOOP`)

Deliverables:

1. `lib/spark_db.py` active schema
2. dual-write adapters
3. contextual memory write path

Gate:

1. parity >= 99.5% on dual-write core tables

Rollback:

1. keep SQLite shadow write, restore legacy reads/writes as canonical

## PR-05: Retrieval Fusion Engine (RRF + Contextual RAG)

Objective:

1. hybrid retrieval: BM25 + semantic + recency + effectiveness
2. contextual retrieval and rerank layer
3. reduce dominant-key collapse and improve relevance

Deliverables:

1. fused ranker + RRF scoring
2. rerank hook
3. retrieval benchmark harness

Gate:

1. replay P@5 and answer utility improve materially vs legacy

Rollback:

1. fallback to legacy retriever route

## PR-06: Advisory Alpha Vertical Slice

Objective:

1. replace advisory hot path with minimal pipeline
2. enforce strict trace binding on all emitted advice
3. add anti-repeat/context-aware dedupe

Deliverables:

1. `advisory_engine_alpha` route
2. route flag canary support
3. comparative emission quality report

Gate:

1. emit rate +5pp, trace coverage >= 50%, no harmful spike

Rollback:

1. route 100% back to legacy advisory path

## PR-07 (Surprise): Self-Play Replay Arena

Objective:

1. build a deterministic replay arena where legacy and alpha compete on identical episodes
2. score by utility, safety, trace integrity, and latency

Why this is a surprise lever:

1. it prevents optimistic bias during refactors
2. it creates a standing benchmark bed for future daily improvements

Deliverables:

1. `scripts/spark_alpha_replay_arena.py`
2. per-run challenger/champion scorecards
3. automatic regression diff artifacts

Gate:

1. alpha must win weighted score in >= 3 consecutive runs before broader canary

Rollback:

1. keep arena as observability-only and block promotion pipeline

## PR-08 (Surprise): Daily Governor (One-Delta RL Policy Loop)

Objective:

1. introduce daily self-improvement governor
2. one bounded policy delta/day
3. replay + canary + auto-rollback

What is new:

1. deterministic governor wraps high-risk RL memory policy so it cannot thrash production
2. explicit champion/challenger promotion ledger

Deliverables:

1. policy action space capped to <= 12 knobs
2. signed policy ledger entries with evidence links
3. rollback automation + freeze switch

Gate:

1. 7 daily cycles, >=3 successful promotions, zero unresolved regressions

Rollback:

1. disable governor scheduler and restore last champion snapshot

## 4) Cutover Decision Rule

Cutover from legacy to alpha only if all pass:

1. retrieval_rate >= 10% and rising
2. strict_trace_coverage >= 50%
3. retrieval guardrail failures do not increase
4. context.p50 >= 80 as alpha floor
5. no critical quality/safety regressions
6. SQLite parity and replay-arena score requirements met

## 5) What This Gives You

1. a real alpha loop with stronger memory construction and retrieval
2. advisory emissions that are both more frequent and more traceable
3. a daily self-improving system that is bounded, auditable, and reversible

