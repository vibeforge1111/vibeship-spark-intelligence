# Spark Alpha Architecture (Current)

## Core Mission
Capture execution signals, convert them into validated intelligence, and deliver pre-tool advisory guidance with measurable outcome attribution.

## Primary Runtime Flow
1. Hook intake: `hooks/observe.py` emits pre/post/prompt events.
2. Advisory runtime: `lib/advisory_engine_alpha.py` handles retrieve -> gate -> synth -> emit.
3. Memory and feedback: `lib/advisor.py` + `lib/meta_ralph.py` capture outcomes and effectiveness.
4. Bridge loop: `lib/bridge_cycle.py` advances queue, memory sync, and distillation-related updates.
5. Readiness checks: `lib/production_gates.py` evaluates alpha production contract.

## Canonical Module Boundaries
- Advisory engine: `lib/advisory_engine_alpha.py`
- Advisory gating and packet state: `lib/advisory_gate.py`, `lib/advisory_packet_store.py`
- Retrieval and ranking: `lib/advisor.py`, `lib/semantic_retriever.py`
- Outcome attribution and quality telemetry: `lib/meta_ralph.py`
- Distillation store and retrieval: `lib/eidos/store.py`, `lib/eidos/retriever.py`, `lib/eidos/integration.py`
- Runtime orchestration: `lib/bridge_cycle.py`, `sparkd.py`
- Config authority: `lib/config_authority.py`, `lib/tuneables_schema.py`
- Observability: `scripts/alpha_intelligence_flow_status.py`, `scripts/alpha_start_readiness.py`, `scripts/alpha_observatory_expand.py`

## Canonical Patterns
- Alpha-only advisory status source: `lib.advisory_engine_alpha.get_alpha_status()`
- Readiness from measurable gates, not qualitative judgment.
- Trace-bound strict attribution required for promotion readiness.
- Observatory pages as first-class operational outputs under `_observatory/`.

## Current Constraints
- Core dependency cycle still exists among `chip_merger/cognitive_learner/eidos.store/meta_ralph/promoter/semantic_retriever/validate_and_store`.
- Docs/runtime drift remains in legacy module references.
- Some monolith hotspots remain and should be reduced in later waves.
