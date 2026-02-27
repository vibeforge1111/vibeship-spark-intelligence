# Spark Alpha Debt Register

## Deferred Items
1. Core cycle break in learning spine
- Risk: medium-high
- Impact: slows change velocity and increases regression risk
- Deferred reason: requires coordinated refactor across critical runtime modules
- Target window: next 1-2 execution waves

2. Large function decomposition (`bridge_cycle`, hook and observatory heavy functions)
- Risk: medium
- Impact: maintainability and testability drag
- Deferred reason: needs behavior-preserving extraction tests first
- Target window: next wave after cycle stabilization

3. Legacy documentation references cleanup (broad sweep)
- Risk: medium
- Impact: operator confusion, onboarding friction
- Deferred reason: breadth is large; should batch by subsystem
- Target window: immediate next docs wave

4. Runtime orphan module triage
- Risk: medium
- Impact: codebase noise and accidental dead-path dependencies
- Deferred reason: requires owner-level keep/archive/delete decisions
- Target window: next 2 weeks

5. Lint debt normalization across 300+ files
- Risk: low-medium
- Impact: readability and consistency debt
- Deferred reason: best done incrementally with touched-file policy
- Target window: ongoing
