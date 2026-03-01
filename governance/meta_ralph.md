# Governance: Meta-Ralph Quality Gate

> **File**: `lib/meta_ralph.py`
> **Role**: Multi-dimensional quality scoring. The primary gatekeeper between "candidate insight" and "stored intelligence."

## Identity

**IS**: A rigorous quality judge that scores proposed learnings across 10 dimensions and rejects anything below threshold. The "roasting" metaphor is deliberate — it challenges insights to prove their worth.

**IS NOT**: A noise filter (that's the cognitive learner's job). Not a dedup engine (that's memory_ops). Not a content analyzer — it scores structural quality, not semantic truth.

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| QUALITY_THRESHOLD must be float, never int | L17: Heuristic labeling drifts | The `int()` bug (3.8→3) was the single biggest quality regression |
| Tautologies must be detected and rejected | L3: Primitives leak through | "The solution is to solve the problem" scores well on surface metrics |
| Platitudes must be detected and rejected | L13: Vague synthesis is low-value | "Consider using best practices" contains no actionable information |
| Circular reasoning must be detected | L4: No-reasoning advice fails | "X is important because X matters" appears to have reasoning but doesn't |
| NEVER bypass the gate for speed | L22: Safety stays in loop | Every bypass is a noise leak that compounds downstream |
| Low-volume pass only for NEEDS_WORK, never PRIMITIVE/NOISE/GARBAGE | L3: Primitives leak | Early sessions need leniency for borderline insights, not for obvious noise |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| Lowering threshold to increase storage volume | More storage ≠ more intelligence — it's more noise | Threshold below 4.0 |
| Scoring based on length alone | Long garbage still fails; short wisdom still passes | Correlation between text length and score >0.8 |
| Allowing tool sequences through because they're "specific" | "Bash→Edit→Bash" is operationally specific but zero intelligence | Tool arrow patterns in stored insights |
| Trusting source credibility without sample count | Source credibility with <5 samples is noise | Source scores applied before MIN_SOURCE_SAMPLES |
| Suppression retest too aggressive | Re-testing suppressed items every hour creates thrashing | INSIGHT_SUPPRESSION_RETEST_AFTER_S < 3600 |

## Socratic Questions

1. **Is 4.0 the right threshold?** What's the actual distribution of scores for insights that proved useful downstream (retrieved, followed, promoted)? What's the distribution for insights that never got used? The ideal threshold sits at the crossover point.

2. **Are our 10 scoring dimensions equally important?** Actionability and specificity might matter more than recency or generality for our use case. Should we weight them? Current: all equal. Should it be?

3. **What's our garbage leakage rate in production?** Benchmark says 6.5%. Is that the same in live operation? What types of garbage are leaking? Are the same patterns repeating?

4. **Are we rejecting good insights?** What's the false rejection rate? If a human reviewed the NEEDS_WORK pile, how many would they promote to QUALITY?

5. **Does the low-volume pass create a warm-up noise problem?** The first 50 events get a lower bar. Does this mean early sessions are polluted with NEEDS_WORK insights that never get cleaned up?

6. **Is the attribution window (1200s / 20 min) long enough?** Some causal chains span hours. If someone hits an error, works around it, then the fix lands 45 minutes later — we miss the causal link.

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Quality pass rate | 20-40% of candidates | Too low = over-filtering; too high = under-filtering |
| Garbage leakage | <3% of stored insights are garbage | Periodic audit of stored insights |
| False rejection rate | <10% of rejected insights are actually valuable | Sample rejected insights, human review |
| Tautology detection rate | >95% of tautologies caught | Feed known tautologies through scoring |
| Score distribution | Bell curve centered around 3-5 | If bimodal, scoring dimensions are fighting |

## Failure Signals

- Pass rate >60% → threshold too low or scoring inflated
- Pass rate <10% → threshold too high or scoring broken
- Same insight type leaking repeatedly → pattern gap in detection
- Score clustering at exactly threshold → gaming or ceiling effect
- NEEDS_WORK pile growing without resolution → no reprocessing pipeline

## Lesson Map

| Lesson | Application |
|--------|------------|
| L1 (telemetry ≠ intelligence) | Rejects tool sequences, timing metrics, file counts |
| L3 (primitives leak) | Multi-dimensional scoring catches single-dimension fakes |
| L4 (no-reasoning fails) | Causal clarity dimension scores cause-effect chains |
| L13 (vague synthesis low-value) | Actionability dimension penalizes "consider/maybe" |
| L17 (heuristic labeling drifts) | Fixed int() bug; threshold must be float |
| L22 (safety in loop) | Never bypassed for speed; low-volume pass is bounded |
