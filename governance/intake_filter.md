# Governance: Intake Filter

> **File**: `lib/intake_filter.py`
> **Role**: First gate. Rejects obvious noise before queueing. No LLM, no I/O, <5ms.

## Identity

**IS**: A lightweight, deterministic bouncer that keeps the queue clean by rejecting events with zero learning potential.

**IS NOT**: A quality judge. It doesn't score intelligence — it rejects guaranteed waste. The quality judgment happens downstream at Meta-Ralph.

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| NEVER filter POST_TOOL_FAILURE events | L1: Raw telemetry ≠ intelligence, BUT failures ARE intelligence | Failures contain the causal signal for learning |
| NEVER filter USER_PROMPT events | L10: Source attribution is mandatory | User intent is the origin of every trace chain |
| NEVER filter mutation tool events (Edit/Write/Bash) | L23: Runtime diverges from intent | Mutations change state — we must observe them |
| NEVER filter SESSION_START/END/STOP | L11: Trace lineage is mandatory | Boundary markers anchor episode tracking |
| Always filter successful Read/Glob/Grep with no error | L1: Raw telemetry ≠ intelligence | A successful file read teaches nothing by itself |
| Fail-open on any internal error | L22: Safety stays in the loop | Better to over-capture than silently drop signals |
| Duplicate detection must be bounded (200 entry cap) | L2: Duplicates compound fast | But the dedup cache itself can't grow unbounded |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| Filtering based on content | Content analysis is Meta-Ralph's job, not intake's | Any regex on event text at this layer |
| Adding LLM calls at intake | Violates <5ms budget, creates latency for every event | Import of any model/API client |
| Filtering errors to reduce noise | Errors are the highest-signal events in the entire system | Any rule that drops events with error fields |
| Trusting tool_name blindly | New tools may be mutation tools we don't recognize | Unknown tools should pass through |
| Persisting filter state to disk | Intake must be stateless across restarts — no cold start penalty | Any file I/O in the filter path |

## Socratic Questions

Questions we must keep asking about intake filtering:

1. **What are we dropping that we shouldn't be?** Run the filter on a week of real events. How many dropped events contain failure signals, user corrections, or unexpected patterns?

2. **Is our "read-only" tool list complete?** When new MCP tools or custom tools are added, do they default to pass-through or silent drop?

3. **Is 2 seconds the right dedup window?** Too short = dupes leak. Too long = legitimate retries get dropped. What does the actual distribution of retry intervals look like?

4. **Is 0.15 the right readiness threshold?** Below 0.15 we drop. But what if a low-readiness event carries a high-value error? (Currently handled: errors override. But are there other high-value signals in low-readiness events?)

5. **Should we track what we drop?** Currently stats are in-memory only. If we never look at what's dropped, how do we know the filter is calibrated correctly?

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Drop rate | 40-60% of total events | `get_intake_filter_stats()["dropped"] / total` |
| False negative rate (noise that passes) | <5% of passed events should be true noise | Sample 100 passed events, manually classify |
| False positive rate (signal that's dropped) | 0% of drops should contain errors or user intent | Audit dropped events for error/prompt content |
| Latency | <5ms per decision | Time the `should_queue_event` call |
| Memory footprint | <50KB for dedup cache | `len(_last_seen)` * ~100 bytes |

## Failure Signals

- Drop rate suddenly jumps to >80% → filter is too aggressive
- Drop rate falls to <10% → filter isn't working or new event types bypass it
- Errors appearing in dropped events → CRITICAL: error detection logic broken
- Dashboard shows "0 events queued" while hook is active → filter is blocking everything

## Lesson Map

| Lesson | Application |
|--------|------------|
| L1 (telemetry ≠ intelligence) | Core purpose: filter telemetry, pass intelligence |
| L2 (duplicates compound) | Consecutive dupe detection within 2s window |
| L5 (session weather over-memorized) | Read-only tool success is session weather |
| L11 (trace lineage mandatory) | Never filter boundary markers (session start/end) |
| L22 (safety in the loop) | Fail-open design — errors pass through |
| L25 (runtime ≠ design) | Stats tracking to observe actual behavior |
