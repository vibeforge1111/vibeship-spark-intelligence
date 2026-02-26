# Health Contract

Spark Intelligence exposes two different concepts:

- Liveness: "process is up"
- Readiness: "system is usable and loops are healthy"

## sparkd

- `GET /health`
  - Purpose: liveness
  - Expected: HTTP 200 with plain body `ok`

- `GET /status`
  - Purpose: readiness + pipeline signal
  - Expected: HTTP 200 JSON with:
    - `ok: true`
    - `now` (unix seconds)
    - `port`
    - `bridge_worker.last_heartbeat`
    - `bridge_worker.pattern_backlog`
    - `bridge_worker.validation_backlog`
    - `pipeline` (when available)

## Observability

See `docs/OBSIDIAN_OBSERVATORY_GUIDE.md` for Observatory setup. Spark Pulse serves web endpoints on port 8765.

## Metric Contract (Alpha)

Canonical contract module:

- `lib/metric_contract.py`
- version: `2026-02-26.alpha.v1`

This contract is the single source of truth for:

- retrieval guardrail thresholds
- cross-surface drift metric definitions
- formula and tolerance metadata

### Canonical Drift Metrics

1. `memory_noise_ratio`
   - canonical metric: `capture.noise_like_ratio`
   - tolerance: `0.03` (absolute)
2. `context_p50_chars`
   - canonical metric: `context.p50`
   - tolerance: `12` chars (absolute)
3. `advisory_emit_rate`
   - canonical metric: `advisory_engine.emit_rate`
   - tolerance: `0.02` (absolute)

Primary scripts:

- `python scripts/memory_quality_observatory.py`
- `python scripts/cross_surface_drift_checker.py`
- `python scripts/production_loop_report.py`

