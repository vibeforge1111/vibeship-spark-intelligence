# Governance: Memory Operations Engine

> **File**: `lib/memory_ops.py`
> **Role**: Decides ADD/UPDATE/DELETE/NOOP for every candidate insight. Replaces binary keep/discard.

## Identity

**IS**: A decision engine that treats memory as a living system — insights can be born (ADD), evolved (UPDATE), invalidated (DELETE), or recognized as redundant (NOOP).

**IS NOT**: A storage engine. It decides what to do; `cognitive_learner.py` does the actual storage. It is NOT a quality judge — Meta-Ralph scores quality before this engine runs.

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| NOOP threshold (0.92 similarity) must be strict | L2: Duplicates compound fast | Near-identical insights waste storage and pollute retrieval |
| DELETE is soft — increment contradictions, don't physically remove | L19: Reversible-step thinking | Hard deletes destroy audit trail and are irreversible |
| Contradiction detection must have word overlap threshold (0.60) | L3: Primitives leak through | Without topic overlap, "Always X" and "Never Y" aren't contradictions |
| Fallback to Jaccard when embeddings unavailable | L25: Runtime ≠ design | Embedding model may be down; dedup must still work |
| UPDATE must preserve the more specific text | L14: Keepability > volume | Merging shouldn't dilute specificity |
| Merged text capped at 500 chars | L1: Raw telemetry ≠ intelligence | Unbounded merge creates rambling insights |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| ADD everything because similarity is low | Fills the store with near-duplicates at 0.74 similarity | Jaccard between stored insights regularly >0.70 |
| Trusting Jaccard alone for dedup | Jaccard misses semantic duplicates ("validate auth" vs "check authentication") | False negative rate >18% without embeddings |
| Hard DELETE on contradiction | Destroys provenance, makes debugging impossible | Any code path that removes insights from JSON |
| Merging without checking which text is better | Can replace a specific insight with a vague one | Merged text shorter or less actionable than original |
| Ignoring activation in DELETE decisions | High-activation insights should be preserved even when contradicted | DELETE of insights with B > 0 without UPDATE |

## Socratic Questions

1. **Is 0.92 the right NOOP threshold?** If we lower it to 0.88, how many more duplicates do we catch? How many legitimate variants do we lose?

2. **Is 0.75 the right UPDATE threshold?** What's the actual distribution of similarity scores for insights that SHOULD be merged? Are we missing merges at 0.73 or creating false merges at 0.76?

3. **Does Jaccard word overlap actually correlate with semantic similarity?** "Rate limiting prevents abuse" and "Abuse prevention through rate limiting" have high semantic overlap but different Jaccard scores. How often does this mismatch matter in practice?

4. **Are we creating UPDATE chains?** If Insight A gets updated to A', then A' gets updated to A'', do we lose the original reasoning? Should we keep a merge history?

5. **What happens when contradictions are wrong?** If the system DELETEs "Always use TypeScript" because someone said "Never use TypeScript for scripts," the DELETE may be contextually wrong. How do we detect and recover from false contradictions?

6. **Are we measuring the right thing?** We track op counts (ADD/UPDATE/DELETE/NOOP). But do we track whether the operations were CORRECT? What's our precision on each operation?

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| NOOP rate | 15-30% of candidates | Duplicates caught before storage |
| UPDATE rate | 10-20% of candidates | Existing insights enriched rather than duplicated |
| DELETE rate | <5% of candidates | Contradictions should be rare |
| ADD rate | 50-70% of candidates | Most candidates should be genuinely new |
| False NOOP rate | <2% | Sample NOOPs — were any legitimately different? |
| False DELETE rate | 0% | Every DELETE must have clear contradiction evidence |

## Failure Signals

- NOOP rate >50% → either too many duplicates entering, or threshold too aggressive
- NOOP rate <5% → dedup isn't working, store is filling with variants
- DELETE rate >15% → contradiction detector is over-triggering
- ADD rate >90% → similarity detection broken, nothing is being merged
- Merged text consistently shorter than originals → merge logic choosing wrong winner

## Lesson Map

| Lesson | Application |
|--------|------------|
| L2 (duplicates compound) | NOOP at 0.92 similarity prevents duplicate storage |
| L3 (primitives leak) | Relies on Meta-Ralph running first — doesn't re-score quality |
| L9 (schema validation) | Contradiction detection validates before mutating |
| L15 (contradiction pressure) | DELETE increments times_contradicted by 5 |
| L19 (reversible steps) | Soft DELETE: marks invalidated, doesn't physically remove |
| L20 (explicit done markers) | Every decision returns MemoryDecision with op + reason |
