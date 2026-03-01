# Governance: Pipeline

> **File**: `lib/pipeline.py`
> **Role**: Orchestrates event processing: intake → classification → gate → store → index. The central nervous system.

## Identity

**IS**: The orchestrator that moves events through the intelligence funnel. It calls Meta-Ralph, memory_ops, cognitive_learner, and semantic_retriever in the right order with the right data.

**IS NOT**: A decision maker itself. It delegates quality to Meta-Ralph, dedup to memory_ops, storage to cognitive_learner, and retrieval to semantic_retriever. The pipeline's job is sequencing and error handling.

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| Gate sequence is fixed: L0 structural → Meta-Ralph → memory_ops → storage | L3: Primitives leak | Skipping any gate creates a noise pathway |
| Every gate failure must be logged with trace_id | L11: Trace lineage mandatory | Silent failures create orphaned events |
| Low-volume bypass NEVER applies to PRIMITIVE/NOISE/GARBAGE | L3: Primitives leak | Even in the first 50 events, obvious garbage must be rejected |
| Memory_ops failure falls back to direct add_insight | L22: Safety in loop | Dedup failure shouldn't block storage of genuinely new insights |
| Activation recording failure is silent, never blocks | L22: Safety in loop | Activation is supplementary scoring, not a gate |
| Semantic indexing failure is silent, never blocks | L22: Safety in loop | Indexing failure means retrieval is degraded, not that storage should fail |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| Adding new gates without governance review | Every gate changes the noise profile of the entire system | New import in _gate_and_store not in governance files |
| Processing events out of order | Causal chains depend on temporal ordering | Events with earlier timestamps processed after later ones |
| Silent error swallowing in gate chain | "Fail-open" is correct, but "fail-silent" hides problems | except blocks with only `pass` and no logging |
| Rate-limiting not enforced per cycle | Unbounded storage in a single cycle creates batch noise | >100 insights stored in one cycle |
| Source defaulting to "pipeline" | Obscures where the insight actually came from | >50% of insights with source="pipeline" |

## Socratic Questions

1. **Is the gate sequence optimal?** We run L0 structural → Meta-Ralph → memory_ops. Should memory_ops (dedup check) run BEFORE Meta-Ralph (quality scoring)? Dedup is cheaper than quality scoring.

2. **What happens to NEEDS_WORK insights?** They're currently passed through during low-volume periods but rejected otherwise. Should there be a queue for NEEDS_WORK insights that get re-scored when more context is available?

3. **How much time does the pipeline spend on noise?** If 70% of events are noise, we're spending 70% of pipeline compute on rejecting things. Would a faster pre-check save meaningful time?

4. **Is trace_id propagated through every step?** If an event enters with trace_id="abc123", does that ID appear in the Meta-Ralph roast, the memory_ops decision, the storage record, and the activation access log?

5. **What's the event processing latency distribution?** If most events process in 50ms but 5% take >5s (LLM scoring), are we holding up the queue for low-value events?

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Events processed per cycle | 50-200 | Bridge cycle stats |
| Gate pass rate (L0) | >95% | Most events should pass structural check |
| Gate pass rate (Meta-Ralph) | 20-40% | Quality gate should reject majority |
| Memory ops ADD rate | 50-70% of post-gate events | Most quality events should be new |
| End-to-end latency (p50) | <100ms per event | Timer around full gate chain |
| End-to-end latency (p99) | <2s per event | Timer around full gate chain |

## Failure Signals

- 0 events processed in a cycle → queue is empty or pipeline is stuck
- >500 events per cycle → queue overflow, possibly processing backlog
- Gate pass rate >80% → quality gates too lenient
- Gate pass rate <5% → quality gates too aggressive or scoring broken
- Source="pipeline" on all insights → source attribution not propagated

## Lesson Map

| Lesson | Application |
|--------|------------|
| L3 (primitives leak) | Multi-gate sequence catches different noise types |
| L11 (trace lineage) | trace_id threaded through all gate decisions |
| L20 (explicit done markers) | Every gate returns verdict/decision with reason |
| L22 (safety in loop) | Fail-open at every gate, never blocks on supplementary failure |
| L25 (runtime ≠ design) | Metrics on actual pass rates vs expected |
