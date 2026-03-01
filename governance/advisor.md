# Governance: Advisory System

> **File**: `lib/advisor.py`
> **Role**: Retrieves relevant insights before tool actions, ranks them by quality+relevance+trust, and emits advice.

## Identity

**IS**: The voice of the system. It surfaces the right insight at the right moment to improve the next action. The final mile — where stored intelligence becomes actionable advice.

**IS NOT**: A search engine. It doesn't just find similar text — it ranks by multi-dimensional quality and suppresses noise. Not a storage system. Not a quality scorer.

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| Only 0.1% of stored insights reach users — this is a feature, not a bug | L14: Keepability > volume | Better to emit nothing than emit noise |
| Source-blind advice MUST be rejected | L10: Source attribution mandatory | "do X" without provenance is unverifiable |
| Noise penalties are multiplicative, not additive | L3: Primitives leak | Additive penalties let garbage score 0.35; multiplicative crushes it to <0.05 |
| Effectiveness decay at 14 days | L16: Unknown outcomes = debt | Advice effectiveness must degrade if we stop measuring it |
| Tool-family cooldowns must be enforced | L2: Duplicates compound | Same advice for every Read call is noise, not help |
| Cross-encoder reranking is optional, never required | L22: Safety in loop | If reranker is down, fall back to rank_score |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| Emitting advice for every tool call | Alert fatigue — user ignores everything | Emission rate >50% of tool calls |
| Raising MIN_RANK_SCORE to reduce noise | Also kills good advice that's contextual but low-scoring | Emission count drops to 0 for days |
| Trusting source tier without effectiveness data | Source tier is a prior; effectiveness is evidence. Evidence > prior | Source with 0 effectiveness observations scoring 0.90 |
| Feedback loop raising ALL boats equally | Positive signal increases noise scores too | Garbage source scores increasing over time |
| Mind slot reservation dominating results | Weak mind memories displacing strong cognitive insights | Mind memories >30% of emitted advice |
| Ignoring suppression reasons | Suppressed advice may be suppressed for wrong reasons | Suppression rate >80% with no analysis |

## Socratic Questions

1. **Is 0.1% emission rate acceptable?** We store ~1000 useful insights. Only ~1 reaches the user per session. Is this because 999 are irrelevant to the current context, or because our ranking is too aggressive?

2. **Do users actually follow the advice?** We track "followed" rates. What's the average? If it's <20%, is our advice useful or just noise the user ignores?

3. **Are source quality tiers calibrated to reality?** EIDOS gets 0.90 trust baseline. But if EIDOS distillations are often generic, is 0.90 deserved? Should tiers be based on measured effectiveness, not assumptions?

4. **What advice would have prevented the last 5 failures?** If we look at recent errors, was there stored advice that SHOULD have been emitted but wasn't? What blocked it — rank score? cooldown? suppression?

5. **Is the feedback loop actually working?** Auto-tuner adjusts source boosts based on outcomes. But with 55.5% effective dampening on cognitive sources, are we actively suppressing our best source?

6. **Should advice be proactive or reactive?** Currently we emit on PRE_TOOL (reactive — "before you do this, consider..."). Should we also emit on patterns (proactive — "you've been editing without reading, you should...")?

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Emission precision | >60% of emitted advice is relevant to the task | Track follow rates |
| Follow rate | >30% of emitted advice is acted on | Compare advice to subsequent actions |
| Noise in emission | 0% of emitted advice is noise/garbage | Audit emitted advice |
| Effectiveness correlation | Positive correlation between effectiveness score and follow rate | Statistical analysis |
| Suppression audit | <20% of suppressions are false (would have been useful) | Sample suppressed advice |

## Failure Signals

- 0 emissions for an entire session → ranking too aggressive or no relevant insights
- >10 emissions per session → ranking too lenient, alert fatigue risk
- Follow rate <10% → advice is irrelevant or untrusted
- Same advice repeating within cooldown → cooldown logic broken
- Effectiveness scores all converging to same value → feedback loop not discriminating

## Lesson Map

| Lesson | Application |
|--------|------------|
| L4 (no-reasoning advice fails) | Noise penalties for "no reasoning" patterns |
| L10 (source attribution) | Source quality tiers with measured effectiveness |
| L12 (self-replay ≠ advice) | Transcript artifact penalty (x0.40) |
| L14 (keepability > volume) | Only top 1-2 insights emitted per event |
| L16 (unknown outcomes = debt) | Effectiveness decay at 14 days |
| L25 (runtime ≠ design) | Auto-tuner adjusts boosts based on actual outcomes |
