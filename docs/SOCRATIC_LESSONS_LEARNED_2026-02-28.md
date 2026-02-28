# Socratic Lessons Learned: Spark Alpha

Date: 2026-02-28  
Branch: feat/spark-alpha

## Why this exists

For one month we kept trying to fix advisory quality with narrow technical patches. We improved mechanics, but not intelligence quality.  
This document captures what we did wrong and what we learned the hard way, using Socratic method.

## Socratic method we will use each cycle

For every failure class, ask in order:
1. What did we assume was true?
2. What evidence contradicted that assumption?
3. What category mistake did we make?
4. What must be true for this to be useful intelligence?
5. What rule do we add so this failure cannot repeat silently?

## What we did wrong (and what it taught us)

## 1) We optimized proxies, not meaning
- Assumption: High emit rate, trace coverage, and follow rate imply good intelligence.
- Contradiction: Promoted/advised content still contained residue (`Chunk ID`, conversational fragments, CSS artifacts).
- Category mistake: Treated plumbing health as advisory quality.
- Hard lesson: Operational metrics are necessary but not sufficient; semantic quality must be measured directly.

## 2) We treated exposure as validation
- Assumption: Repeatedly seen items are reliable.
- Contradiction: Noise items accumulated high validations and were promoted.
- Category mistake: Confused co-occurrence with causality.
- Hard lesson: Validation must require relevance and outcome linkage, not mere exposure.

## 3) We stored residue as intelligence
- Assumption: Anything "technical-looking" can be memory.
- Contradiction: Error fragments and transient telemetry dominated memory/advisories.
- Category mistake: Mixed chronicle truth (what happened) with advisory truth (what to do).
- Hard lesson: Residue belongs in diagnostics, not long-lived intelligence memory.

## 4) We asked narrow questions, then got narrow fixes
- Assumption: Regex/threshold tweaks would solve system quality.
- Contradiction: New noise variants bypassed patches; useful guidance sometimes got dropped.
- Category mistake: Solved symptoms instead of ontology.
- Hard lesson: Define "worth keeping" first, then encode rules.

## 5) We lacked explicit keepability criteria
- Assumption: Existing gates were enough.
- Contradiction: High-confidence low-meaning content passed.
- Category mistake: Gate without first-principles contract.
- Hard lesson: Intelligence must pass Actionability, Context-fit, Causal confidence, Transfer, and Decay policy.

## 6) We accepted black-box suppression
- Assumption: Gate suppressions are fine even if reason is unknown.
- Contradiction: Could not tune or trust suppression behavior.
- Category mistake: Operational opacity in a quality-critical component.
- Hard lesson: Every block/drop decision must carry machine-readable reason codes.

## 7) We conflated "followed" with "helpful"
- Assumption: If tools succeed after advice, advice helped.
- Contradiction: Tool success often independent of advice quality.
- Category mistake: Outcome adjacency instead of counterfactual usefulness.
- Hard lesson: Helpfulness needs explicit and causal signals, split by human vs heuristic labels.

## 8) We underused context in observability
- Assumption: Last 5 or 10 samples are enough.
- Contradiction: Large-scale contamination patterns were invisible in tiny windows.
- Category mistake: Small-sample confidence illusion.
- Hard lesson: Inspect 100+ item cohorts with end-to-end traces.

## 9) We promoted before rewrite
- Assumption: Raw captured text can be promoted if score is high.
- Contradiction: Conversation replay and session-weather artifacts reached promoted learnings.
- Category mistake: No transformation boundary between raw capture and durable guidance.
- Hard lesson: Potentially useful fragments must be rewritten into condition -> action -> rationale.

## 10) We over-trusted plan completion signals
- Assumption: "PR delivered" and "tests passing" means solved.
- Contradiction: Core semantic failure persisted despite successful delivery checkboxes.
- Category mistake: Delivery completeness vs problem completeness.
- Hard lesson: Success criteria must include content audits against real data.

## 11) We allowed stale/legacy assumptions to linger
- Assumption: Old paths and old assumptions were still active.
- Contradiction: Audits mixed alpha and legacy interpretations.
- Category mistake: Runtime truth drift.
- Hard lesson: Keep a strict runtime contract and verify source-of-truth at read time.

## 12) We automated before defining judgment
- Assumption: Auto-tuning can discover quality without explicit quality ontology.
- Contradiction: System tuned toward proxy wins while semantic quality degraded.
- Category mistake: Premature autonomy.
- Hard lesson: First learn human judgment boundaries; then automate against verified judgments.

## Non-negotiable rules going forward

1. No memory entry without keepability contract.
2. No promotion without human-legible meaning and transfer value.
3. No quality claim without context-linked evidence.
4. No gate drop without reason code.
5. No blended helpfulness KPI; always split human, heuristic, implicit.
6. No advisory quality conclusion from proxy metrics alone.
7. No optimization pass before 100+ item contextual cohort review.
8. No replay arena "win" that ignores emission relevance quality.
9. No long-lived storage for session-bound telemetry residue.
10. No self-improvement step without proving causal lift.

## Practical review checklist (Socratic, weekly)

1. Which items did we keep that no future operator would thank us for?
2. Which useful items did we incorrectly drop, and why?
3. Which gate reason dominates and is it truly protective?
4. Which source is over-weighted relative to its semantic quality?
5. Which promoted items fail transfer outside their original trace?
6. Which KPI changed, and what item-level evidence explains it?

If we cannot answer these from traces, observability is insufficient.

