# Spark V2 Risk-Balanced Adoption Plan

Date: 2026-02-26
Branch: feat/simplification-hard-reset
Status: execution-ready decisions

## 1) Why We Should Move Now (Data Snapshot)

Current loop health from live commands/reports:

- Production gates: `13/19` passed (`NOT READY`)
  - `retrieval_rate = 0.0%` (target `>=10%`)
  - `strict_acted_on_rate = 5.14%` (target `>=20%`)
  - `strict_trace_coverage = 14.39%` (target `>=50%`)
  - `advisory_readiness = 0.0` (target `>=0.40`)
  - `advisory_freshness = 0.0` (target `>=0.35`)
  - `meta_ralph_quality_rate = 6.94%` (target band `30%-60%` when enforced)
- Memory observatory (2026-02-26T19:10:29Z):
  - capture count `0`
  - context p50 `0`
  - advisory emit rate `0.0`
  - dominant key ratio `0.4` (fails `<=0.35`)
  - guardrails failing `3/7`
- Recent advisory decisions: last `6` rows are all `blocked` with `advice_count=0`.
- Local stores are empty now:
  - `~/.spark/memory_store.sqlite` memories: `0`
  - `~/.spark/cognitive_insights.json` entries: `0`

Interpretation: the system is not primarily "too complex but functioning" right now; it is in a degraded no-supply state (almost no usable memory/advice material flowing through).

## 2) Adopt Now vs Defer (From Simplification Plan)

## Adopt Now (Aggressive but Controlled)

### A1. Phase 2: Unified Noise Classifier (YES)
- Why now: highest leverage for reducing contradictory filters and restoring predictable intake.
- Risk: medium.
- Control: keep old filters in shadow mode for one week; compare disagreement rate.

### A2. Phase 8 (partial): Simplified scorer path behind flag (YES)
- Why now: current Meta-Ralph quality band is failing hard; simplified scoring can restore throughput.
- Risk: high.
- Control: dual-score each candidate (`legacy_score`, `simple_score`), promote only when either agrees with allowlist constraints; rollback by flag.

### A3. Phase 3 (partial): Advisory engine vertical slice (YES)
- Scope now: `retrieve -> rank -> gate -> emit` hot path only.
- Why now: recent ledger shows `advice_count=0`; hot-path clarity is more urgent than feature completeness.
- Risk: high.
- Control: keep legacy route as fallback adapter; canary at 10% session sampling.

### A4. Phase 1 (partial): SQLite dual-write + read-shadow for active path (YES)
- Scope now: events, insights, advisory decisions only.
- Why now: current state fragmentation makes debugging impossible.
- Risk: medium-high.
- Control: no hard cutover yet; dual-write checksums + parity report before any read switch.

### A5. Phase 10: Shared utility extraction (YES)
- Why now: low-risk cleanup that reduces bug surface during fast refactors.
- Risk: low.
- Control: mechanical refactor with focused tests.

## Defer Until Loop Is Alive Again

### D1. Phase 4: Full memory compaction engine (DEFER)
- Reason: compaction is low value while memory volume is near zero.

### D2. Phase 5: graph linking / one-hop traversal (DEFER)
- Reason: adds complexity before baseline retrieval recovers.

### D3. Phase 6: full Thompson sampling + cross-domain transfer (DEFER)
- Reason: recent outcome volume is too low for stable priors.

### D4. Phase 7: broad config + env variable purge (DEFER)
- Reason: removes knobs while we still need diagnostics and controlled recovery.

### D5. Phase 9: deleting large existing test surface (DEFER)
- Reason: keep safety net until new behavioral suite is stable.

## 3) Risk Budget (How We Move Fast Without Breaking Further)

Use exactly 3 high-risk bets in parallel, each with hard rollback:

1. `Bet-H1`: simplified scorer flag path.
2. `Bet-H2`: advisory hot-path slice route.
3. `Bet-H3`: SQLite dual-write active state.

Non-negotiable safeguards:

1. Every bet ships behind a feature flag default-off.
2. Every bet writes side-by-side evidence artifacts (legacy vs new).
3. Auto-rollback trigger if any of these happen for 2 consecutive checkpoints:
   - emit rate drops below baseline by `>20%` relative.
   - strict trace coverage drops by `>10pp` absolute.
   - retrieval guardrail failures increase.

## 4) Execution Order (Fastest Path To Stable Improvement)

### Wave 1 (today): Restore signal + observability
1. Implement A1 (noise classifier) in shadow mode.
2. Implement A2 (simple scorer) dual-score mode.
3. Add loop-alive heartbeat metrics: candidate_count, accepted_count, advice_count.

### Wave 2 (next): Restore user-visible advice flow
1. Implement A3 hot-path advisory slice behind route flag.
2. Canary route at low traffic; compare emission quality and follow outcomes.

### Wave 3: Stabilize persistence and remove drift
1. Implement A4 dual-write + parity report.
2. Keep legacy read path as canonical until parity is stable.

### Wave 4: Cleanups that reduce future spaghetti
1. Implement A5 utility extraction.
2. Start targeted deletions only for code fully replaced in Waves 1-3.

## 5) Definition of "Recovered Enough"

Before broader simplification/deletions, require all of:

1. `retrieval_rate >= 10%` for 24h.
2. `strict_trace_coverage >= 40%` trending to 50%.
3. `advice_count > 0` on >=80% of pre-tool decisions in active sessions.
4. `capture_count > 0` and `context.p50 > 60`.
5. No parity drift incidents above tolerance for dual-write metrics.

At that point, proceed to deferred phases (D1-D5) in order.
