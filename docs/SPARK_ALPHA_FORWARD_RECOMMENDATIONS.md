# Spark Alpha Forward Recommendations (3-6 Months)

## What To Build Next
1. Cycle-break interfaces for the learning spine
- Introduce explicit ports for outcome attribution and memory persistence.
- Goal: decouple `meta_ralph`/`cognitive_learner`/`eidos.store`/`promoter`.

2. Contract tests for critical intelligence flow
- Standardize replay + readiness + pre/post hook contracts as required CI gates.

3. Docs-runtime parity automation
- Add a checker that fails CI when docs reference deleted runtime modules.

4. Focused monolith extraction
- Extract pure functions from `lib/bridge_cycle.py` and `hooks/observe.py`.
- Keep external behavior unchanged and verify with smoke + replay evidence.

## Expected Pressure Points
1. Coupling pressure in the memory/advisory spine under rapid feature changes.
2. Observability drift if pages are not regenerated with each release.
3. Config complexity growth unless tuneable ownership remains explicit.

## Architectural Bets To Make Now
1. Treat strict attribution as a hard contract (not optional telemetry).
2. Keep alpha advisory routing single-path and remove compatibility branches aggressively.
3. Preserve observability-as-code: every critical change updates an observatory page or metric.
