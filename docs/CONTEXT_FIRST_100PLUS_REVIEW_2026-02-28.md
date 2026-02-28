# Context-First 100+ Cohort Review (Memory -> Advisory)

Date: 2026-02-28
Branch: feat/spark-alpha

## Scope

This review intentionally starts from context tables, not headline metrics.
The new Observatory surfaces reviewed were:
- `intelligence_constitution.md`
- `keepability_gate_review.md`
- `context_trace_cohorts.md`
- `intelligence_signal_tables.md`

These pages inspect 100+ real rows across capture, memory, retrieval, emission, and outcome chains.

## What We Are Actually Storing (Context Findings)

1. Memory is still absorbing operational residue as if it were intelligence.
- Many memory rows are chunk IDs, tool-failure fragments, and task-notification residue.
- These entries are coherent as diagnostics, but not reusable as user guidance.

2. Advisory emissions are often "failure weather reports" instead of next-best-action guidance.
- Frequent pattern: "tool failed then recovered" variants repeated across traces.
- These messages are situational status blurbs, not decision leverage.

3. Trace chains are semantically incomplete.
- In many traces, retrieval and emission are present while capture context or outcome context is missing.
- This makes causal interpretation weak even when flow mechanics look healthy.

4. False wisdom formation is visible end-to-end.
- Some rows look strong in validation/follow-through mechanics yet are still non-keepable telemetry.
- This confirms proxy success can still preserve low-meaning content.

5. Compounding table exposes mixed quality.
- It surfaces real reusable patterns (e.g., path verification / oversized read handling).
- It also surfaces conversational artifacts that must be rewritten before long-lived memory.

## Zoomed-Out Interpretation

The core issue is category confusion:
- `ops residue` (what happened in tooling) is being treated as `intelligence` (what should guide next decisions).

Until this distinction is enforced at each stage boundary, downstream tuning will mostly optimize noise transport.

## Keepability Decisions To Enforce Next (Rule Intent, Not Thresholds)

1. Capture boundary
- Keep: user intent, task constraints, environment assumptions.
- Quarantine: raw failure payloads, chunk IDs, command stderr dumps.

2. Memory boundary
- Keep only entries that can be rewritten as: `condition -> action -> why`.
- If entry cannot be rewritten into that shape, decay it quickly.

3. Retrieval boundary
- If retrieval route is empty or context-poor, do not emit generic fallback advice.
- Prefer no advisory over residue advisory.

4. Emission boundary
- Emission text must contain a concrete next action tied to the current tool/task.
- Session weather summaries should stay in observability, not advisory text.

5. Outcome boundary
- Treat follow-through as weak evidence.
- Keep explicit causal evidence separate from implicit success adjacency.

## Step-by-Step Execution Order

1. Run daily context-first review using the new pages and annotate false wisdom examples.
2. Add stage rules that enforce keepability shape before persistence and emission.
3. Re-run context tables and validate that conversational/telemetry residues are reduced in memory and advisories.
4. Only after context quality stabilizes, re-introduce metric gates as secondary checks.

## Immediate Next Patch Set

- Add a memory firewall pre-persist path for telemetry/conversational residues.
- Add an emission guard that blocks non-actionable "tool recovered" advisories.
- Add trace completeness tags (`capture_present`, `retrieval_present`, `outcome_present`) so semantic gaps are explicit per trace.
