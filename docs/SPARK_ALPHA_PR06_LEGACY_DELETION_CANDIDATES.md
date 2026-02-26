# Spark Alpha PR-06 Legacy Deletion Candidates

Date: 2026-02-26  
Branch: `feat/spark-alpha`

Purpose: explicit legacy advisory-path candidates for PR-10 deletion sweep, tied to the new alpha route.

## Cut Conditions Before Deletion

1. Replay arena passes: alpha wins weighted score for 3 consecutive runs.
2. Live canary passes with no safety/guardrail regression.
3. `production_loop_report.py` remains `READY` for 3 consecutive runs.
4. Route mode has stayed `alpha` (or `canary>=50%`) without rollback events for the agreed burn-in window.

## Candidate Set (Post-Validation)

1. `hooks/observe.py` legacy fallback block to direct `advisor.advise` when orchestrator/engine throws.
2. `lib/advisory_engine.py` quick fallback branch (`LIVE_QUICK_FALLBACK_ENABLED`) once alpha path proves stable.
3. `lib/advisory_engine.py` packet fallback emit branch (`PACKET_FALLBACK_EMIT_ENABLED`) once alpha no-emit loop rate stays in target.
4. `lib/advisory_engine.py` duplicate post-gate dedupe pass if alpha gate+state dedupe proves equivalent or better.
5. `lib/advisory_engine.py` legacy route-only diagnostic fields superseded by alpha comparison report.
6. `lib/advisor.py` keyword fallback path for cognitive retrieval when semantic+RRF path consistently outperforms in replay.
7. `lib/advisor.py` superseded single-path rank weighting branches replaced by deterministic fusion stack.
8. `lib/advisory_parser.py` legacy read paths not consumed by alpha or replay observability.

## Files Added in PR-06 That Enable This Sweep

1. `lib/advisory_engine_alpha.py`
2. `lib/advisory_orchestrator.py`
3. `scripts/advisory_alpha_quality_report.py`

## Rollback Note

If any deletion candidate causes regression, set `SPARK_ADVISORY_ROUTE=engine` and restore removed block(s) from rollback tag.

