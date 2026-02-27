# ADR-2026-02-28: Alpha Transition Precision Execution

## Status
Accepted

## Context
Spark is in alpha transition. The runtime is operational, but phase-1 audit identified drift in docs/config references, high coupling zones, and observability gaps for readiness blockers, strict attribution funnel, and dependency health.

## Decision
Adopt a wave-based execution model that prioritizes:
1. No-harm baselining before functional changes.
2. Alpha-authoritative runtime paths only.
3. Observatory-first execution where each major transition has explicit visibility.
4. Single-source references for transition evidence.

## Implementation
1. Wave 0 baseline captured through:
- `scripts/alpha_start_readiness.py --strict --emit-report`
- `scripts/alpha_intelligence_flow_status.py --json-only`
- `python -m lib.integration_status`
2. Legacy advisory runtime fallback removed from `spark/cli.py` so advisory status is alpha-authoritative.
3. Observatory expansion implemented via `scripts/alpha_observatory_expand.py`, generating:
- `_observatory/alpha_readiness_blockers.md`
- `_observatory/strict_attribution_funnel.md`
- `_observatory/distillation_yield.md`
- `_observatory/config_and_docs_drift.md`
- `_observatory/dependency_health.md`
4. Outputs are mirrored to Obsidian vault `_observatory/` using `lib.observatory.config`.

## Consequences
Positive:
- Less runtime ambiguity for advisory status.
- Faster operator visibility on blockers and drift.
- Explicit dependency/coupling signal exposed in the Observatory.

Negative:
- Observatory now reports legacy-doc drift more explicitly; visible debt may increase short-term perceived instability.
- Dependency health page currently relies on latest saved audit snapshot and must be refreshed as code changes.

## Rollback
1. Revert commit touching `spark/cli.py` if runtime status behavior regresses.
2. Delete `scripts/alpha_observatory_expand.py` and generated pages if observability outputs are noisy or invalid.

## Verification
1. `python scripts/alpha_start_readiness.py --strict --episodes 2 --seeds 1 --delta-rounds 1 --pytest-targets tests/test_production_loop_gates.py --emit-report`
2. `python scripts/alpha_observatory_expand.py`
3. `python scripts/alpha_intelligence_flow_status.py --json-only`
