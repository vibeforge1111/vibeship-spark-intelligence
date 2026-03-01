# Governance: Semantic Retriever

> **File**: `lib/semantic_retriever.py`
> **Role**: Hybrid retrieval engine combining embedding similarity, word overlap, recency (ACT-R), and effectiveness scoring.

## Identity

**IS**: The search engine for intelligence. Given a query (tool context, user intent), it finds the most relevant insights from the cognitive store and ranks them for the advisor.

**IS NOT**: A quality judge. It retrieves by relevance, not quality. Noise can be highly relevant to a query but still be garbage. Quality filtering happens upstream (Meta-Ralph) and downstream (advisor ranking).

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| ACT-R activation is primary recency signal when available | L15: Contradiction pressure | Power-law decay naturally demotes unused insights; exponential is too aggressive |
| Fallback to exponential half-life when activation unavailable | L22: Safety in loop | If activation DB is down, retrieval must still work |
| Noise filtering runs during retrieval | L12: Self-replay ≠ advice | Even if noise leaked into storage, it shouldn't reach the user |
| Fusion formula weights must sum to 1.0 | L9: Schema validation | Weights >1.0 inflate scores; <1.0 deflate them |
| Record retrieval access for every activated insight | L11: Trace lineage | Retrieval access is the link between storage and advisory emission |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| Semantic similarity as sole retrieval signal | Ignores recency, effectiveness, and quality dimensions | Fusion formula with semantic weight >0.70 |
| Word overlap matching without stopword removal | "the", "is", "a" match everything, inflating scores | High overlap scores on unrelated insights |
| Recomputing embeddings on every retrieval | O(n) cost per query scales poorly with store size | Retrieval latency growing linearly with insight count |
| Not caching retrieval results | Same query repeated within seconds recomputes everything | Identical queries within 30s |
| Hardcoded half-life decay | 60-day half-life means 6-month-old insights still score 0.25 | Very old insights appearing in top-5 results |

## Socratic Questions

1. **Is 0.40 semantic + 0.30 recency + 0.20 effectiveness + 0.10 other the right balance?** If we increase recency weight, we favor fresh-but-shallow insights. If we increase effectiveness, we favor proven-but-possibly-outdated advice. What does the data say?

2. **Should we pre-filter by category?** If the query is about "React state management," should we only search in wisdom/reasoning categories, or should we also check self_awareness and context insights?

3. **Is the sigmoid normalization of activation correct?** `sigmoid(activation)` maps high activation to ~1.0 and low to ~0.5. But 0.5 is not "low recency" — it's "medium." Should the floor be lower?

4. **How many insights can we search before latency becomes a problem?** At 50 insights, retrieval is fast. At 500, it's slower. At 5000, it may be unusable. What's our growth trajectory?

5. **Are we retrieving the right things for the right queries?** The benchmark shows P@5 = 0.520. That means ~2.5 of the top 5 results are relevant. Can we get to 0.700?

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| P@5 (Precision at 5) | >= 0.52 (current), target 0.70 | Retrieval quality benchmark |
| Retrieval latency (p50) | <50ms | Timer around retrieve() |
| Retrieval latency (p99) | <500ms | Timer around retrieve() |
| Noise in top-5 results | 0% | Audit retrieved results for noise |
| ACT-R activation coverage | >80% of insights have activation scores | Compare activation DB to cognitive store |

## Failure Signals

- P@5 drops below 0.40 → retrieval quality regression
- Retrieval latency >1s consistently → store too large or embeddings slow
- Same insights always appearing in top results regardless of query → scoring bias
- Activation scores all 0.0 → activation store not wired or DB broken
- Noise appearing in top-5 results → noise filter bypass

## Lesson Map

| Lesson | Application |
|--------|------------|
| L11 (trace lineage) | Records retrieval access in activation store |
| L14 (keepability > volume) | Fusion scoring ranks by multiple quality dimensions |
| L15 (contradiction pressure) | ACT-R decay naturally demotes insights not being used |
| L22 (safety in loop) | Fallback to exponential decay when activation unavailable |
| L25 (runtime ≠ design) | Benchmark measures actual P@5, not assumed quality |
