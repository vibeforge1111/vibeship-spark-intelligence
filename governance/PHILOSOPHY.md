# Intelligence Governance Philosophy

## What Is Intelligence?

Intelligence is not volume. It is not retention. It is not recall speed.

Intelligence is the ability to **act differently next time because of what was learned**.

An insight that never changes a decision is noise wearing a costume.
A memory that compounds — that makes the next memory more valuable — is intelligence.

## The 25 Hard-Way Lessons (Governance Foundation)

These are earned truths. Every governance rule traces back to at least one.

| # | Lesson | Governance Implication |
|---|--------|----------------------|
| 1 | Raw telemetry is not intelligence | Gate: reject anything that reads like a log line |
| 2 | Duplicates compound fast | Gate: dedup before storage, not after |
| 3 | Primitives leak through weak gates | Gate: enforce quality early, not just late |
| 4 | "No reasoning" advice fails | Gate: require causal chain or evidence |
| 5 | Session weather gets over-memorized | Gate: transient state is not insight |
| 6 | Read-before-edit discipline matters | Operational, not learnable — filter out |
| 7 | Path assumptions are fragile | Operational — filter out |
| 8 | Large-file reads fail without chunking | Operational — filter out |
| 9 | Schema validation prevents breakage | Gate: validate before merge |
| 10 | Source attribution is mandatory | Trace: every insight must name its source |
| 11 | Trace lineage is mandatory | Trace: capture -> store -> retrieve -> emit must be linked |
| 12 | Self-replay should not be advice | Gate: detect conversation echo |
| 13 | Vague synthesis is low-value | Gate: "consider/maybe/perhaps" without evidence = reject |
| 14 | Keepability must beat volume | Metric: fewer, better > more, worse |
| 15 | Reliability needs contradiction pressure | Mechanism: contradictions must weaken, not just fail silently |
| 16 | Unknown outcomes create debt | Metric: unlabeled rows are a liability |
| 17 | Heuristic-only labeling drifts | Gate: calibrate against ground truth periodically |
| 18 | Small testable proof before edit | Practice: verify before mutate |
| 19 | Reversible-step thinking reduces risk | Practice: prefer soft delete over hard delete |
| 20 | Explicit "done" markers improve quality | Metric: every operation needs a completion signal |
| 21 | Promote only evidence-backed learnings | Gate: promotion requires trace + validation count |
| 22 | Safety stays in the loop during optimization | Constraint: never bypass gates for speed |
| 23 | Runtime can diverge from design intent | Metric: observe actual behavior, not assumed behavior |
| 24 | Bot/noise patterns look legitimate at first glance | Gate: pattern detection over content trust |
| 25 | Architecture intent is not runtime truth | Mandate: observability is not optional |

## The Three Questions Every System Must Answer

Before any insight enters, moves through, or exits a system:

1. **Would a human find this useful next time?** If no — it's noise.
2. **Can we trace where this came from and why it's here?** If no — it's an orphan.
3. **Does this change a future decision?** If no — it's dead weight.

## Governance File Contract

Each system's governance file (`governance/<system>.md`) contains:

- **Identity**: What this system IS and IS NOT
- **Hard Rules**: Non-negotiable constraints derived from failures
- **Anti-Patterns**: Known failure modes with examples
- **Socratic Questions**: What we must keep asking ourselves
- **Success Metrics**: How we know it's working
- **Failure Signals**: How we know it's broken
- **Lesson Map**: Which of the 25 lessons apply and how

These files are **living documents**. When a new failure teaches us something, the relevant governance file gets updated. When a rule proves wrong, it gets revised with the reason.

## The Intake Principle

The most important governance happens at the edges — where raw events first touch the intelligence layer. A bad insight that enters the system:

- Consumes storage
- Pollutes retrieval results
- Degrades advisory quality
- May get promoted to user-facing files
- Compounds with other bad insights

**Cost of a false positive at intake >> cost of a false negative at intake.**

It's better to drop a marginal insight and re-discover it later than to store garbage that poisons downstream systems.
