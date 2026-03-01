# Governance: Cognitive Learner

> **File**: `lib/cognitive_learner.py`
> **Role**: Stores domain insights (reasoning, wisdom, self-awareness) and filters operational noise via 51+ pattern rules.

## Identity

**IS**: The memory store. It holds the insights that the rest of the system retrieves, promotes, and acts on. It's also the secondary noise gate — catching patterns Meta-Ralph's scoring misses.

**IS NOT**: A primary quality judge (that's Meta-Ralph). Not a retrieval engine (that's semantic_retriever). Not a decision maker about what to do with insights (that's memory_ops).

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| Cycle summary entries MUST be filtered | L5: Session weather over-memorized | 89/143 insights were "Cycle summary:" telemetry — this single pattern destroyed retrieval |
| Tool sequence patterns MUST be rejected | L1: Raw telemetry ≠ intelligence | "Bash→Edit→Read" patterns dominated the store |
| Conversational fragments MUST be rejected | L12: Self-replay ≠ advice | "Do you think...", "Can you...", "Let's..." are conversation, not insight |
| Code dumps MUST be rejected | L1: Raw telemetry ≠ intelligence | >5 indented lines is code, not learning |
| Noise patterns must have phase awareness (storage vs retrieval) | L14: Keepability > volume | Some patterns should block storage but allow retrieval of already-stored items |
| `_save_insights_now()` MERGES with disk — use `drop_keys` to delete | L9: Schema validation prevents breakage | Without drop_keys, "deleted" insights reappear from disk merge |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| Adding noise patterns without testing | False positives block valid insights silently | New pattern blocks "Always hash passwords" or similar valid text |
| Pattern list growing without consolidation | 51 patterns is already near-unmaintainable | Adding pattern #52 without removing or merging existing ones |
| Backfilling actionable_context when it's missing | Obscures whether the insight was ACTUALLY actionable at capture | `if not context: context = "..."` patterns in add_insight |
| Dual-gate confusion (legacy + unified) | Two overlapping noise gates with different rules = unpredictable behavior | Same text blocked by one gate, passed by other |
| Not recording what's filtered | Can't improve filters we can't observe | No logging/stats on which patterns trigger |

## Socratic Questions

1. **How many of our 51 noise patterns have actually triggered in the last 30 days?** If pattern #23 (screenshot paths) hasn't triggered in a month, is it protecting us or is it dead code adding complexity?

2. **Are we running two conflicting noise gates?** The legacy `_is_noise_insight()` has 51 patterns. The unified `classify_noise()` has 41+ patterns. Do they agree? When they disagree, which wins? Should we consolidate?

3. **What's in the store RIGHT NOW that shouldn't be?** If we audited every insight in `cognitive_insights.json`, what percentage would a human classify as noise? The benchmark said 62% in the past. Where are we now?

4. **Are "vague observation" patterns too aggressive?** Pattern #10 blocks "seems to", "appears to", "might be". But "React seems to re-render unnecessarily when state changes" contains real signal. Are we filtering context-dependent value?

5. **Should insights have an expiry?** An insight from 6 months ago about a deprecated API is actively harmful. But we never expire stored insights. Should we?

6. **Is the 250-char length threshold for "very long text" correct?** Some of our best insights are detailed. Does length correlate with noise, or are we penalizing thoroughness?

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Store noise rate | <10% of stored insights are noise | Periodic audit of cognitive_insights.json |
| Noise pattern trigger rate | >80% of patterns have triggered in 30 days | Track per-pattern hit counts |
| False positive rate | <5% of rejections are valid insights | Sample rejected texts, human review |
| Store growth rate | <10 new insights per day (steady state) | Track store size over time |
| Retrieval quality | P@5 >= 0.52 | Run retrieval quality benchmark |

## Failure Signals

- Store size growing >50 insights/day → noise is leaking through both gates
- Store size frozen for days → everything is being rejected (over-filtering)
- Retrieval quality dropping → new noise insights polluting search results
- Same noise category appearing repeatedly → pattern gap
- `_save_insights_now()` errors or lock contention → `.cognitive.lock` stale

## Lesson Map

| Lesson | Application |
|--------|------------|
| L1 (telemetry ≠ intelligence) | 51 noise patterns target telemetry formats |
| L2 (duplicates compound) | Dedup before add_insight via memory_ops |
| L5 (session weather) | Cycle summary, tool usage counts explicitly filtered |
| L12 (self-replay ≠ advice) | Conversational fragments detected and blocked |
| L13 (vague synthesis) | "seems to/appears to/might be" patterns |
| L14 (keepability > volume) | Phase-aware filtering (storage vs retrieval) |
