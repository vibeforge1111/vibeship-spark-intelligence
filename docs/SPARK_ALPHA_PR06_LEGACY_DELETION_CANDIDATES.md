# Spark Alpha PR-06 Legacy Deletion Candidates

Date: 2026-02-27  
Branch: `feat/spark-alpha`

Purpose: explicit legacy advisory-path candidates for PR-10 deletion sweep, tied to the new alpha route.

## Cut Conditions Before Deletion

1. Replay arena passes: alpha wins weighted score for 3 consecutive runs.
2. Live canary passes with no safety/guardrail regression.
3. `production_loop_report.py` remains `READY` for 3 consecutive runs.
4. Route mode has stayed `alpha` (or `canary>=50%`) without rollback events for the agreed burn-in window.

## Candidate Set (Post-Validation)

1. [Done] `hooks/observe.py` legacy fallback block to direct `advisor.advise` when orchestrator/engine throws.
2. [Done] `lib/advisory_engine.py` quick fallback branch (`LIVE_QUICK_FALLBACK_ENABLED`).
3. [Done] `lib/advisory_engine.py` packet fallback emit branch (`PACKET_FALLBACK_EMIT_ENABLED`).
4. [Done] `lib/advisory_orchestrator.py` default route cut over to `alpha`; engine retained only as explicit route (no auto-fallback).
5. [Done] `lib/advisory_engine.py` duplicate post-gate text-signature dedupe pass collapsed into the existing emission-quality filter (`49fd5c9`).
6. [Done] `lib/advisory_engine.py` legacy route-only diagnostics parameter threading removed from diagnostics envelope (`49fd5c9`).
7. [Done] `lib/advisor.py` keyword fallback path for cognitive retrieval removed.
8. [Done] `lib/advisor.py` superseded per-profile/domain rank-weight branches collapsed to one deterministic fusion-weight baseline with explicit override support retained (`1b53c38`).
9. [Done] `lib/advisory_parser.py` legacy markdown/engine preview read paths removed.
10. [Done] `lib/advisory_engine.py` dead global dedupe helper functions removed after dedupe path collapse (`8936beb`).

## Files Added in PR-06 That Enable This Sweep

1. `lib/advisory_engine_alpha.py`
2. `lib/advisory_orchestrator.py`
3. `scripts/advisory_alpha_quality_report.py`

## Rollback Note

If any deletion candidate causes regression, set `SPARK_ADVISORY_ROUTE=engine` and restore removed block(s) from rollback tag.
