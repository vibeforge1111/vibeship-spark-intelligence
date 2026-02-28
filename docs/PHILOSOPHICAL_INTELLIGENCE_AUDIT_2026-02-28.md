# Philosophical Audit: What Is Worth Keeping as Intelligence

Date: 2026-02-28
Branch: feat/spark-alpha

## Method (Context-First)

I inspected real stored artifacts directly, not dashboards first:
- Cognitive store: 140 newest entries from `~/.spark/cognitive_insights.json`
- Promotion trail: 80 recent entries from `~/.spark/promotion_log.jsonl`
- Advisory emissions: 100-item mid-late segment from `~/.spark/advisory_emit.jsonl`
- Trace-linked quality events: 218 emission/quality trace joins from `~/.spark/advisor/advisory_quality_events.jsonl`
- Promoted context file: `CLAUDE.md`

This is a qualitative reading of meaning, not a metric-only pass.

## Central Philosophical Finding

The system conflates three different kinds of truth:

1. **Chronicle truth**: what happened (`exec_command failed: Chunk ID: ...`).
2. **Operational truth**: what often breaks (`33% failure rate`, transient failure weather).
3. **Advisory truth**: what should be done next in this moment.

Spark currently stores (1) and (2) as if they were (3).

That is the root category error.

## What the Data Actually Shows

### A. Residue Masquerading as Intelligence

Observed repeatedly in memory, promoted learnings, and emissions:
- `exec_command failed: Chunk ID: ...`
- `Tool X failed then recovered ...`
- `codex session: 1/4 tool results failed ...`
- conversational echoes (`it worked, can we now run the localhost`)
- sentiment artifacts (`User expressed satisfaction with the response`)
- raw CSS/code fragments (`#sky-egg { ... }`)

These items have historical value for diagnostics, but almost no future planning value for advisory decisions.

### B. Why False Wisdom Looks Convincing

Many low-meaning items look "strong" due to these mechanics:
- repeated exposure -> high `times_validated`
- temporal adjacency to successful tool run -> `helpful` or `followed`
- promotion criteria over-weighting reliability counts without semantic transfer checks

So the system learns: "frequently observed" equals "worth remembering".

But frequency is not wisdom.

### C. Explicit Helpfulness Is Partly Epistemically Corrupted

In a deep sample of explicit-helpful quality events, many "helpful" advisories are still generic failure-weather statements or brittle EIDOS phrasing tied to path artifacts.

Meaning: explicit labels exist, but many labels are judging compliance/continuation, not causal advisory usefulness.

## Casebook: Keep / Rewrite / Drop

### Drop (Residue)

1. `exec_command failed: Chunk ID: d20032`
- Why drop: opaque identifier, no transferable strategy, no action path.

2. `User expressed satisfaction with the response`
- Why drop: affect signal, not action signal.

3. `Tool 'Edit' failed then recovered in claude session`
- Why drop: session weather, not guidance.

4. `codex session: 1/3 tool results failed ...`
- Why drop: monitoring telemetry; should stay in observability pane.

### Rewrite (Potential but malformed)

1. `Read failed: File content exceeds maximum tokens`
- Rewrite to keepable: `If Read exceeds token limit, use offset+limit chunking before semantic extraction.`

2. `Be cautious with Bash due to transient failures`
- Rewrite to keepable: `When Bash fails once on path-heavy commands, retry once with normalized quoted path before fallback.`

3. `Validate authentication inputs`
- Rewrite to keepable: add boundary and trigger (`at API ingress`, `before token parse`, `reject on schema mismatch`).

### Keep (Compounding)

1. `Assumption 'File exists at expected path' often wrong. Use Glob first.`
- Why keep: concrete action, broad transfer across tasks, clear boundary condition.

2. `Verify contracts before changing payload shapes.`
- Why keep: causal relevance to regressions, reusable development principle.

3. `Use offset/limit for oversized Read payloads.`
- Why keep: directly converts failure class into deterministic operator action.

## Ontology for Keepability (Before New Rules)

An entry is intelligence only when it satisfies all five:

1. **Actionability**: contains a concrete next action.
2. **Context-boundedness**: says when/where it applies.
3. **Causal plausibility**: links action to expected outcome.
4. **Transferability**: useful beyond one local trace.
5. **Decay discipline**: explicit expiry or revalidation trigger.

If any of these fail, the item is not yet intelligence.

## Hard Conclusion

Current memory behaves like an event scrapbook with confidence scores.
It is not yet a disciplined advisory knowledge base.

The fix is not "better thresholds first".
The fix is ontological:
- separate residue channels from advisory-memory channels,
- require rewrite into `condition -> action -> rationale` shape,
- and only then allow promotion and influence.

## Immediate Next Step (Still Pre-Optimization)

Before adding new optimization rules, run one manual adjudication pass over 120 items each cycle with this question:

"Would a future operator thank us for seeing this sentence again in a different task context?"

If no, it belongs in diagnostics, not intelligence.
