# Governance: ACT-R Activation Store

> **File**: `lib/activation.py`
> **Role**: Power-law frequency-recency scoring. Determines which insights are "alive" vs "dormant."

## Identity

**IS**: A cognitive science-backed scoring system that models human memory activation. Insights used frequently and recently have high activation; forgotten insights decay naturally.

**IS NOT**: A quality score. High activation means "frequently accessed," not "good." A bad insight can have high activation if it keeps getting retrieved. Quality is Meta-Ralph's job.

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| Return 0.0 on any database error, never crash | L22: Safety stays in loop | Activation is supplementary; failure must not block the pipeline |
| Record access on every retrieval, validation, storage, and advisory emission | L11: Trace lineage mandatory | Access records ARE the lineage — they prove an insight was used |
| Prune to 200 accesses per insight maximum | L14: Keepability > volume | Unbounded access logs create storage pressure |
| Cache TTL of 30s — never serve stale activation indefinitely | L25: Runtime ≠ design | Stale cache means retrieval scoring is based on old data |
| MIN_TIME_DELTA = 1.0s to prevent log(0) | L18: Small testable proof | Mathematical safety guard against division by zero |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| Recording access for noise insights | Inflates activation of garbage, making it harder to filter | Noise insights appearing in high-activation list |
| Not recording access for retrievals | Activation score stops reflecting actual usage | Insights with many retrievals showing 0 activation |
| Using activation as the ONLY retrieval score | Ignores quality, relevance, and freshness dimensions | Popular-but-wrong insights dominating results |
| Pruning most recent accesses instead of oldest | Destroys recency signal, the most valuable dimension | Access log for a key showing only old timestamps |
| Crossing process boundaries with in-memory cache | Different processes see different activation scores | Advisor and pipeline disagreeing on activation for same key |

## Socratic Questions

1. **Is decay=0.5 the right exponent?** ACT-R literature uses 0.5 as default, but our insights aren't human memories. Should domain-specific insights decay slower (0.3)? Should operational hints decay faster (0.7)?

2. **Should access types be weighted differently?** A `validation` access (someone confirmed this insight) is arguably worth more than a `retrieval` access (it was surfaced but maybe ignored). Should we weight access types in the BLA formula?

3. **What does activation=0.0 actually mean?** Currently it means either "never accessed" or "single access within 1 second." These are very different situations. Should we distinguish them?

4. **Is 200 the right access log cap?** For an insight accessed 10 times/day, 200 entries = 20 days of history. Is that enough to distinguish "consistently valuable" from "recently popular"?

5. **Are we actually using activation to change decisions?** If activation only adds 0.3 weight to the trust dimension in advisor scoring, is the SQLite database overhead justified? What's the measured impact on retrieval quality?

6. **What happens to insights that are dormant but still true?** "Never commit secrets to git" might have low activation if it hasn't been triggered recently, but it's permanently true. Should some insights be exempt from decay?

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Access recording rate | 100% of retrieval/validation/storage events | Compare access_log count to known retrieval count |
| Cache hit rate | >80% of activation lookups served from cache | Track cache hits vs misses |
| Activation correlation with usefulness | Positive correlation | Compare activation rank with advisor effectiveness rank |
| DB size | <10MB after 30 days | `ls -la ~/.spark/activation/access_log.sqlite` |
| Prune effectiveness | 0 insights with >200 access records | SQL query for counts |

## Failure Signals

- All activations returning 0.0 → database connection broken
- Activation scores never changing → access recording not wired
- DB growing >50MB → pruning not running in bridge_cycle
- High-activation insights consistently scored as noise by Meta-Ralph → activation inflating garbage
- Cache TTL violations → stale activations persisting >60s

## Lesson Map

| Lesson | Application |
|--------|------------|
| L11 (trace lineage) | Access records create the lineage chain |
| L14 (keepability > volume) | Power-law decay naturally demotes unused insights |
| L15 (contradiction pressure) | Low-activation + contradiction → DELETE decision |
| L16 (unknown outcomes = debt) | Unrecorded accesses mean activation is wrong |
| L22 (safety in loop) | Returns 0.0 on error, never crashes |
| L25 (runtime ≠ design) | Cache TTL prevents stale scoring |
