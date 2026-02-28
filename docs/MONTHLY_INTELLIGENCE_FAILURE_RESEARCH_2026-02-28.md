# Monthly Research: How We Built an "Intelligence" Loop Around Non-Intelligence

Date: 2026-02-28  
Branch analyzed: `feat/spark-alpha`  
Window analyzed: 2026-01-28 to 2026-02-28

## Executive conclusion

We did a large amount of real engineering work, but repeatedly optimized delivery mechanics and proxy metrics before locking a stable definition of intelligence quality.  
The result was a high-activity system that often moved residue faster and more reliably.

## Evidence base

## 1) Commit volume and pace

- Total commits in window: `1269`
- Peak days:
  - `2026-02-27`: `215`
  - `2026-02-28`: `74`
  - `2026-02-21`: `75`
  - `2026-02-22`: `67`

Interpretation:
- We were not blocked by effort; we were blocked by epistemic framing.

## 2) Where effort went (commit-touch scope)

Commit-level touch counts (same commit can touch multiple areas):

- `lib/*` touched in `673` commits
- docs/readme/project surfaces touched in `520` commits
- `tests/*` touched in `383` commits
- `scripts/*` touched in `233` commits
- advisory-related paths touched in `383` commits
- memory-related paths touched in `190` commits
- retrieval-related paths touched in `54` commits
- quality/meta-ralph related paths touched in `114` commits
- observability-related paths touched in `127` commits

Interpretation:
- Strong investment in advisory wiring, docs, and operational tooling.
- Relatively less sustained investment in retrieval semantics and intelligence-content correctness loops.

## 3) Most frequently changed files

Top examples:

- `lib/advisor.py` (`107` touches)
- `docs/SPARK_ALPHA_IMPLEMENTATION_STATUS.md` (`99`)
- `CLAUDE.md` (`83`)
- `lib/advisory_engine.py` (`72`)
- `lib/bridge_cycle.py` (`68`)
- `README.md` (`64`)
- `config/tuneables.json` (`59`)
- `docs/SPARK_ALPHA_FUSION_10PR_PLAN.md` (`59`)
- `lib/cognitive_learner.py` (`52`)
- `lib/meta_ralph.py` (`47`)

Interpretation:
- Hotspot concentration confirms we iterated heavily on orchestration and control surfaces.
- High plan/status churn suggests strategy adaptation was frequent; this can help learning but also diffuses focus if ontology is unsettled.

## 4) Commit-subject theme frequency

Keyword occurrences in commit subjects (non-exclusive):

- `advis*`: `256`
- `docs`: `218`
- `fix`: `164`
- `feat`: `147`
- `refactor`: `76`
- `test`: `70`
- `gate`: `65`
- `observ*`: `64`
- `retriev*`: `54`
- `memory`: `49`
- `quality`: `49`
- `noise`: `26`
- `semantic`: `18`
- `meta-ralph`: `17`
- `emit`: `16`

Interpretation:
- We spent much more commit narrative on advisory infrastructure than on semantic validity signals.
- This is not proof of failure by itself, but it is consistent with the observed quality drift pattern.

## 5) Plan-vs-reality documentary evidence

From plan docs:
- `SPARK_ALPHA_REBUILD_PLAN.md` prioritizes unified noise handling, simplified scorer, advisory hot path, and bounded policy loop.
- `SPARK_ALPHA_8PR_EXECUTION_PLAN.md` includes PR-05 retrieval fusion and PR-08 daily governor with replay/canary/rollback.

From reality audit:
- `SPARK_ALPHA_8PR_REALITY_AUDIT_2026-02-28.md` states PR-05 is active but quality-partial.
- Same audit states PR-08 tooling exists but is not operationalized as always-on governance.
- Same audit calls out intelligence-quality calibration as top remaining risk.

Interpretation:
- Core architecture direction was often correct.
- Execution closed many technical loops but left semantic-quality governance under-enforced.

## Socratic diagnosis (assumption -> contradiction -> lesson)

## A1. "If the loop is active and traceable, intelligence quality is improving."
- Contradiction: Emissions and promotions still included residue classes.
- Lesson: Loop vitality is not intelligence quality.

## A2. "Reliability and validation counts indicate memory value."
- Contradiction: Exposure-driven validation inflated low-value content.
- Lesson: Co-occurrence cannot stand in for causal usefulness.

## A3. "Replay/canary wins imply advisory quality wins."
- Contradiction: Arena/governance often scored mechanics, not meaning.
- Lesson: Benchmarks must include semantic relevance and keepability quality.

## A4. "More gates/telemetry will naturally converge quality."
- Contradiction: Untargeted gates caused blind suppression and unknown-reason debt.
- Lesson: Gates need reason codes and ontology-aligned acceptance criteria.

## A5. "We can tune first and define intelligence later."
- Contradiction: Tuning amplified proxy-success behavior.
- Lesson: Define intelligence contract first; tune only after.

## A6. "Plan completion means problem completion."
- Contradiction: PR completion and test health coexisted with content contamination.
- Lesson: Delivery status must be subordinate to semantic outcome audits.

## Circular patterns we repeated

1. Detect noisy outcome -> add patch/gate/tuneable.
2. Metrics recover at system level.
3. Same failure class reappears in slightly new form.
4. Add another patch.
5. Repeat.

Root driver:
- We repeatedly patched manifestations of residue without stabilizing a single invariant definition of what should count as intelligence memory/advice.

## What changed recently that breaks the loop

Recent commits on 2026-02-28 added meaningful structural shifts:

- L0 keepability gate before persistence.
- Intake lifecycle ledger with stage/action/reason tracing.
- Latest-100 advisory reverse lineage observability.
- Explicit false-positive fix for actionable contract guidance.

These are directionally correct because they move quality enforcement earlier and make failures inspectable at item level.

## Non-negotiable research conclusions

1. Intelligence ontology is the primary bottleneck, not throughput.
2. Traceability without semantic adjudication is a false comfort.
3. High commit velocity can hide conceptual drift.
4. Plan proliferation is dangerous unless tied to stable quality invariants.
5. Every quality claim must be auditable through item-level evidence.

## What we should study next (targeted)

1. Counterfactual helpfulness design:
- How to estimate causal lift vs adjacent tool success.

2. Keepability agreement modeling:
- Human-vs-automated agreement on keep/rewrite/drop over rolling 100-item cohorts.

3. Source contamination economics:
- Which source path introduces the highest residue per useful advisory lift.

4. Context compression integrity:
- Where compaction loses condition/action/rationale structure.

5. Promotion stability:
- How to prevent promote/demote oscillation while retaining adaptability.

## Definition of "intelligence progress" for next month

Progress is real only if all are true simultaneously:

1. Stored memory is predominantly reusable guidance, not residue.
2. Emitted advisory is context-actionable at decision time.
3. Helpfulness reflects causal confidence, not proxy success.
4. Promotion surfaces remain residue-free under 100+ item cohort review.
5. Governance loops can explain every keep/drop/emit/suppress decision in plain reason codes.

