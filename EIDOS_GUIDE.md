# EIDOS Guide: The Complete Intelligence System

**EIDOS** = **E**xplicit **I**ntelligence with **D**urable **O**utcomes & **S**emantics
Navigation hub: `docs/GLOSSARY.md`

> "Intelligence = compression + reuse + behavior change. Not storage. Not retrieval. **Enforcement.**"

---

## Table of Contents

1. [Core Philosophy](#core-philosophy)
2. [The Vertical Loop](#the-vertical-loop)
3. [The Six Layers](#the-six-layers)
4. [Core Primitives](#core-primitives)
5. [Guardrails (Hard Gates)](#guardrails-hard-gates)
6. [Memory Gate](#memory-gate)
7. [Evidence Store](#evidence-store)
8. [Escalation](#escalation)
9. [Validation](#validation)
10. [Metrics & Success](#metrics--success)
11. [Flow Charts](#flow-charts)
12. [Integration Points](#integration-points)
13. [CLI Commands](#cli-commands)
14. [Checklist: Are We Following EIDOS?](#checklist-are-we-following-eidos)
15. [Consolidated Architecture Notes](#consolidated-architecture-notes)

---

## Consolidated Architecture Notes

This guide now absorbs key points from archived architecture supplements.

Integrated from archived docs:
- `docs/archive/root/EIDOS_ARCHITECTURE.md`
- `docs/archive/root/EIDOS_ARCHITECTURE_ADDITIONS.md`

Key merged notes:
1. Evidence before modification gate:
   - after repeated failed edits on the same target, require diagnostic evidence before additional code edits.
2. Layered evidence handling:
   - keep ephemeral tool evidence separate from canonical memory and enforce retention by evidence type.
3. Distillation and reuse remain the acceptance criteria:
   - storage volume is not a success metric unless later reuse measurably improves outcomes.
4. Control-plane first behavior:
   - phase control, budget guards, and stuck-state checks should block low-quality loops before more tool actions.

---

## Core Philosophy

### The Problem We Solved

Intelligence wasn't compounding because:

| Problem | Symptom |
|---------|---------|
| **Thrashing** | Fix loops and rabbit holes without learning |
| **Forgetting to write** | Stopped storing after initial phase |
| **Not reading** | Retrieval wasn't binding (optional, not enforced) |
| **No enforcement** | LLM decided everything, no guardrails |

### The Solution

```
OLD: "How do we store more?"
NEW: "How do we force learning?"
```

EIDOS enforces learning through:
- **Mandatory decision packets** (not just logs)
- **Prediction loops** (predict before, evaluate after)
- **Memory binding** (must cite memory or blocked)
- **Distillation** (experience → reusable rules)
- **Control plane** (watchers, phases, budgets)

---

## The Vertical Loop

Every action goes through the vertical loop:

```
┌─────────────────────────────────────────────────────────────────┐
│                    THE EIDOS VERTICAL LOOP                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   1. ACTION          What are we doing?                         │
│        ↓                                                        │
│   2. PREDICTION      What do we expect? (confidence 0-1)        │
│        ↓                                                        │
│   3. OUTCOME         What actually happened?                    │
│        ↓                                                        │
│   4. EVALUATION      Did prediction match? (PASS/FAIL/PARTIAL)  │
│        ↓                                                        │
│   5. POLICY UPDATE   What rule changes?                         │
│        ↓                                                        │
│   6. DISTILLATION    What's the reusable lesson?                │
│        ↓                                                        │
│   7. MANDATORY REUSE Retrieved memories MUST be cited           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Loop Execution

```python
# PreToolUse
prediction = make_prediction(tool_name, tool_input)  # Step 2
step, decision = create_step_before_action(...)      # Steps 1, 2, check policies

# PostToolUse / PostToolUseFailure
step = complete_step_after_action(...)  # Steps 3, 4, 5, 6

# SessionEnd
episode = complete_episode(...)  # Triggers full distillation
```

---

## The Six Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                    EIDOS ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Layer 5: DISTILLATION ENGINE                                  │
│   └── Post-episode reflection, rule extraction                  │
│                                                                 │
│   Layer 4: REASONING ENGINE (LLM)                               │
│   └── Constrained by Control Plane                              │
│                                                                 │
│   Layer 3: CONTROL PLANE                                        │
│   └── Watchers, budgets, phase control, guardrails              │
│                                                                 │
│   Layer 2: SEMANTIC INDEX                                       │
│   └── Embeddings for retrieval (never source of truth)          │
│                                                                 │
│   Layer 1: CANONICAL MEMORY (SQLite)                            │
│   └── Source of truth: Episodes, Steps, Distillations, Policies │
│                                                                 │
│   Layer 0: EVIDENCE STORE                                       │
│   └── Ephemeral audit trail with retention policies             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

| Layer | What | Purpose |
|-------|------|---------|
| **0. Evidence** | Tool outputs, test results | Ephemeral proof (72h-90d retention) |
| **1. Canonical** | Episodes, Steps, Distillations | Source of truth (permanent) |
| **2. Semantic** | Embeddings | Fast retrieval (never authoritative) |
| **3. Control** | Watchers, budgets, phases | Enforcement (deterministic) |
| **4. Reasoning** | LLM | Thinking (constrained by L3) |
| **5. Distillation** | Reflection engine | Rule extraction (post-episode) |

---

## Core Primitives

### Episode

A bounded learning unit with a goal.

```python
Episode(
    episode_id="ep_abc123",
    goal="Implement user authentication",
    success_criteria="Login, logout, session management working",
    constraints=["Use existing User model", "No external auth providers"],
    budget=Budget(max_steps=50, max_time_seconds=1800),
    phase=Phase.EXECUTE,  # ORIENT, PLAN, EXECUTE, VALIDATE, CONSOLIDATE, ESCALATE
    outcome=Outcome.IN_PROGRESS,  # SUCCESS, PARTIAL, FAILURE, IN_PROGRESS
)
```

### Step (Decision Packet)

Every action is a decision packet, not just a log.

```python
Step(
    # Identity
    step_id="step_xyz789",
    episode_id="ep_abc123",

    # BEFORE action (mandatory)
    intent="Fix the login bug",
    decision="Edit auth.py to fix validation",
    alternatives=["Rewrite auth module", "Add logging first"],
    assumptions=["File exists", "Bug is in validation logic"],
    prediction="Edit will succeed and fix the bug",
    confidence_before=0.7,

    # Action
    action_type=ActionType.TOOL_CALL,
    action_details={"tool": "Edit", "file_path": "auth.py"},

    # Memory binding (CRITICAL)
    retrieved_memories=["dist_001", "dist_002"],
    memory_cited=True,  # MUST be True or action blocked

    # AFTER action (filled by complete_step)
    result="Edit succeeded",
    evaluation=Evaluation.PASS,
    surprise_level=0.0,  # 0=expected, 1=completely surprised
    lesson="Validation logic fix pattern works",
    confidence_after=0.8,

    # Validation
    validated=True,
    validation_method="test:passed",
)
```

### Distillation

Extracted rules from experience.

```python
Distillation(
    distillation_id="dist_001",
    type=DistillationType.HEURISTIC,  # HEURISTIC, SHARP_EDGE, ANTI_PATTERN, PLAYBOOK, POLICY
    statement="Always Read file before Edit to verify content matches",
    domains=["file_operations", "editing"],
    triggers=["Edit", "file modification"],
    source_steps=["step_xyz789"],
    validation_count=5,
    contradiction_count=0,
    confidence=0.85,
)
```

### Policy

Operating constraints that must be respected.

```python
Policy(
    policy_id="pol_001",
    statement="Never commit directly to main branch",
    scope="git_operations",  # or "GLOBAL"
    priority=90,  # Higher = more important
    source="USER",  # USER, SYSTEM, LEARNED
)
```

---

## Guardrails (Hard Gates)

Guardrails are **non-negotiable**. They block actions, not suggest.

### Guardrail 1: Progress Contract

```
┌─────────────────────────────────────────────────────────────────┐
│  PROGRESS CONTRACT                                              │
├─────────────────────────────────────────────────────────────────┤
│  Every action MUST advance toward the goal.                     │
│                                                                 │
│  Blocked if: No measurable progress after N steps               │
│  Action: Require re-planning or escalation                      │
└─────────────────────────────────────────────────────────────────┘
```

### Guardrail 2: Memory Binding

```
┌─────────────────────────────────────────────────────────────────┐
│  MEMORY BINDING                                                 │
├─────────────────────────────────────────────────────────────────┤
│  Retrieved memories MUST be cited in action rationale.          │
│                                                                 │
│  Blocked if: memory_cited == False when memories exist          │
│  Action: Force acknowledgment of relevant past experience       │
└─────────────────────────────────────────────────────────────────┘
```

### Guardrail 3: Outcome Enforcement

```
┌─────────────────────────────────────────────────────────────────┐
│  OUTCOME ENFORCEMENT                                            │
├─────────────────────────────────────────────────────────────────┤
│  Predictions MUST be compared to outcomes.                      │
│                                                                 │
│  Blocked if: Step completes without evaluation                  │
│  Action: Force prediction vs. outcome comparison                │
└─────────────────────────────────────────────────────────────────┘
```

### Guardrail 4: Loop Watchers

| Watcher | Trigger | Action |
|---------|---------|--------|
| **Repeat Error** | Same error 2x | Diagnostic phase + new hypothesis |
| **No-New-Info** | 5 steps without evidence | Stop; data-gather plan |
| **Diff Thrash** | Same file modified 3x | Freeze file, focus elsewhere |
| **Confidence Stagnation** | Delta < 0.05 for 3 steps | Force alternative or escalate |

### Guardrail 5: Phase Control

```
┌─────────────────────────────────────────────────────────────────┐
│  PHASE CONTROL                                                  │
├─────────────────────────────────────────────────────────────────┤
│  Certain actions are ONLY allowed in certain phases.            │
│                                                                 │
│  ORIENT:     Read, Glob, Grep (exploration only)                │
│  PLAN:       Read, Glob, Grep (no execution)                    │
│  EXECUTE:    All tools (with validation)                        │
│  VALIDATE:   Bash (tests), Read (verification)                  │
│  CONSOLIDATE: Read, Write (documentation)                       │
│  ESCALATE:   Read only (gathering context for escalation)       │
│                                                                 │
│  Blocked if: Tool not allowed in current phase                  │
│  Action: Phase violation error with required phase              │
└─────────────────────────────────────────────────────────────────┘
```

### Guardrail 6: Evidence Before Modification (NEW)

```
┌─────────────────────────────────────────────────────────────────┐
│  EVIDENCE BEFORE MODIFICATION                                   │
├─────────────────────────────────────────────────────────────────┤
│  After 2 failed edit attempts, agent FORBIDDEN to edit until:   │
│                                                                 │
│  □ Reproducing the issue reliably                               │
│  □ Narrowing scope with investigation                           │
│  □ Identifying discriminating signal                            │
│  □ Creating minimal reproduction                                │
│                                                                 │
│  Blocked if: edit_fail_count >= 2 AND no diagnostic evidence    │
│  Action: Force diagnostic phase                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Memory Gate

Not everything becomes durable memory. Steps must **earn** persistence.

### Importance Scoring

| Signal | Weight | Description |
|--------|--------|-------------|
| **Impact** | +0.3 | Unblocked progress, solved problem |
| **Novelty** | +0.2 | New pattern not seen before |
| **Surprise** | +0.3 | Prediction ≠ Outcome significantly |
| **Recurrence** | +0.2 | Seen 3+ times across episodes |
| **Irreversible** | +0.4 | Security, production, data loss risk |

**Score > 0.5 → Durable memory**
**Score ≤ 0.5 → Cache with expiry (24-72h)**

### What Gets Promoted

```
┌─────────────────────────────────────────────────────────────────┐
│  PROMOTE (Durable)              │  CACHE (Ephemeral)            │
├─────────────────────────────────┼───────────────────────────────┤
│  "Health=300 for game balance"  │  "Read → Edit sequence"       │
│  "User prefers iterative fixes" │  "Tool had 93% success"       │
│  "Auth bug was in validation"   │  "File modified at 10:43"     │
│  "Never deploy on Friday"       │  "Bash command took 2.3s"     │
└─────────────────────────────────┴───────────────────────────────┘
```

---

## Evidence Store

Ephemeral audit trail with retention policies.

### Retention Policies

| Evidence Type | Retention | Examples |
|---------------|-----------|----------|
| **TOOL_OUTPUT** | 72 hours | Command results, file contents |
| **TEST_RESULT** | 7 days | Test runs, lint outputs |
| **BUILD_ARTIFACT** | 7 days | Build logs, compilation output |
| **DEPLOY_LOG** | 30 days | Deployment records |
| **SECURITY_EVENT** | 90 days | Auth failures, permission denials |
| **USER_FLAGGED** | Permanent | Explicitly marked important |

### Evidence Creation

```python
Evidence(
    evidence_id="ev_001",
    step_id="step_xyz789",
    type=EvidenceType.TEST_RESULT,
    content="All 47 tests passed",
    metadata={"test_count": 47, "duration_ms": 1234},
    expires_at=time.time() + (7 * 24 * 3600),  # 7 days
)
```

---

## Escalation

Structured help requests when stuck.

### Escalation Types

| Type | Trigger | What's Needed |
|------|---------|---------------|
| **BUDGET** | Steps or time exceeded | User approval to continue |
| **LOOP** | Same error 3+ times | Human insight on root cause |
| **CONFIDENCE** | Confidence stuck < 0.3 | Direction or clarification |
| **BLOCKED** | External dependency | Access, credentials, info |
| **UNKNOWN** | Unclassified blocker | Investigation help |

### Request Types

| Type | Use When |
|------|----------|
| **INFO** | Need information to proceed |
| **DECISION** | Need user to choose between options |
| **HELP** | Need hands-on assistance |
| **REVIEW** | Need verification of approach |

### Escalation Structure

```yaml
escalation:
  summary:
    goal: "Implement OAuth login"
    progress: "50% - Basic flow working"
    blocker: "Token refresh fails intermittently"

  attempts:
    - what: "Added retry logic"
      result: "Still fails 20% of time"
    - what: "Increased timeout"
      result: "No improvement"

  evidence:
    - type: "logs"
      content: "TokenExpiredError at refresh:47"
    - type: "reproduction"
      content: "curl -X POST /refresh -d '{token: ...}'"

  hypothesis: "Race condition in token validation"

  request:
    type: HELP
    specific_ask: "Review token refresh logic"
    options:
      - "Add mutex lock"
      - "Implement token queue"
      - "Use different auth library"
```

---

## Validation

Every claim requires validation.

### Standard Validation Methods

| Method | Meaning |
|--------|---------|
| `test:passed` | Automated tests pass |
| `test:failed` | Automated tests fail |
| `build:success` | Build completes successfully |
| `build:failed` | Build fails |
| `lint:clean` | Linter reports no issues |
| `lint:warnings` | Linter has warnings |
| `output:expected` | Output matches expectation |
| `output:unexpected` | Output differs from expectation |
| `manual:verified` | Human verified |
| `manual:rejected` | Human rejected |

### Deferred Validation

Some validations can't happen immediately.

| Deferral Type | Max Wait | Use Case |
|---------------|----------|----------|
| `deferred:needs_deploy` | 24h | Need to deploy to verify |
| `deferred:needs_data` | 48h | Need real data to verify |
| `deferred:needs_human` | 72h | Need human review |
| `deferred:async_process` | 4h | Async job needs to complete |

```python
DeferredValidation(
    validation_id="val_001",
    step_id="step_xyz789",
    method="deferred:needs_deploy",
    created_at=time.time(),
    max_wait_hours=24,
    reminder_sent=False,
)
```

---

## Metrics & Success

### North Star: Compounding Rate

```
                    Steps citing memory that succeeded
Compounding Rate = ────────────────────────────────────
                    Total steps citing memory
```

**Target: > 40%** (memory makes actions more likely to succeed)

### Key Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| **Reuse Rate** | Steps citing memory / Total steps | > 40% |
| **Memory Effectiveness** | Success rate with memory - without | > 10% |
| **Loop Suppression** | Avg retries per error type | < 3 |
| **Distillation Quality** | Useful distillations / Total | > 60% |
| **Outcome Improvement** | Time-to-success decrease | -20%/month |

### Weekly Report

```yaml
weekly_intelligence_report:
  period: "2026-01-27 to 2026-02-02"

  compounding_rate: 0.47  # 47% - above target!

  memory:
    reuse_rate: 0.42
    effectiveness: 0.15
    new_distillations: 12

  efficiency:
    avg_steps_to_goal: 23
    loop_suppression: 2.1
    escalations: 3

  top_learnings:
    - "Auth tokens need 5min buffer before expiry"
    - "Always check file encoding before read"
    - "User prefers short, focused PRs"
```

---

## Flow Charts

### Tool Execution Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                     TOOL EXECUTION FLOW                              │
└──────────────────────────────────────────────────────────────────────┘

      User Request
           │
           ▼
    ┌──────────────┐
    │ PreToolUse   │
    │   Hook       │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐     ┌─────────────────────┐
    │ Make         │────►│ save_prediction()   │
    │ Prediction   │     └─────────────────────┘
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐     ┌─────────────────────┐
    │ EIDOS: Create│────►│ Check Guardrails    │
    │ Step         │     │ Check Control Plane │
    └──────┬───────┘     └─────────┬───────────┘
           │                       │
           │              ┌────────┴────────┐
           │              │                 │
           ▼              ▼                 ▼
    ┌──────────────┐  BLOCKED?         ALLOWED
    │ Tool         │     │                 │
    │ Executes     │◄────┘                 │
    └──────┬───────┘                       │
           │                               │
     ┌─────┴─────┐                         │
     │           │                         │
  SUCCESS     FAILURE                      │
     │           │                         │
     ▼           ▼                         │
┌─────────┐ ┌─────────┐                    │
│PostTool │ │PostTool │                    │
│Use      │ │Failure  │                    │
└────┬────┘ └────┬────┘                    │
     │           │                         │
     ▼           ▼                         │
┌─────────────────────┐                    │
│ EIDOS: Complete Step│◄───────────────────┘
│ - Evaluate prediction                    │
│ - Calculate surprise                     │
│ - Extract lesson                         │
│ - Score for memory                       │
│ - Capture evidence                       │
└─────────────────────┘
           │
           ▼
    ┌──────────────┐
    │ Phase        │
    │ Transition?  │
    └──────────────┘
```

### Episode Lifecycle

```
┌──────────────────────────────────────────────────────────────────────┐
│                     EPISODE LIFECYCLE                                │
└──────────────────────────────────────────────────────────────────────┘

    Session Start
         │
         ▼
  ┌─────────────┐
  │ ORIENT      │  Understand the problem
  │ Phase       │  (Read, Glob, Grep only)
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │ PLAN        │  Design approach
  │ Phase       │  (Read, Glob, Grep only)
  └──────┬──────┘
         │
         ▼
  ┌─────────────┐
  │ EXECUTE     │  Do the work
  │ Phase       │  (All tools allowed)
  └──────┬──────┘
         │
    ┌────┴────┐
    │         │
 SUCCESS   BLOCKED
    │         │
    ▼         ▼
┌─────────┐ ┌─────────────┐
│VALIDATE │ │ ESCALATE    │
│ Phase   │ │ Phase       │
│(tests)  │ │(help req)   │
└────┬────┘ └──────┬──────┘
     │             │
     ▼             │
┌─────────────┐    │
│CONSOLIDATE  │◄───┘
│ Phase       │
│(distill)    │
└─────────────┘
         │
         ▼
   Session End
   (Distillation runs)
```

### Distillation Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                     DISTILLATION FLOW                                │
└──────────────────────────────────────────────────────────────────────┘

    Episode Completes
          │
          ▼
   ┌──────────────┐
   │ Gather All   │
   │ Steps        │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Reflect on   │  What worked? What surprised us?
   │ Episode      │  What patterns emerged?
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Generate     │  Candidate distillations
   │ Candidates   │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Score Each   │  Impact, Novelty, Generalizability
   │ Candidate    │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Check for    │  Does this contradict existing rules?
   │ Conflicts    │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ Save to      │  Canonical memory (SQLite)
   │ Store        │
   └──────────────┘
```

---

## Integration Points

### Hook Integration

EIDOS integrates via `hooks/observe.py`:

```python
# PreToolUse
if EIDOS_AVAILABLE:
    step, decision = create_step_before_action(
        session_id, tool_name, tool_input, prediction
    )
    if not decision.allowed:
        sys.stderr.write(f"[EIDOS] BLOCKED: {decision.message}\n")

# PostToolUse / PostToolUseFailure
if EIDOS_AVAILABLE:
    complete_step_after_action(
        session_id, tool_name, success, result_or_error
    )

# SessionEnd
if EIDOS_AVAILABLE:
    complete_episode(session_id, Outcome.SUCCESS)
```

### Configuration

EIDOS settings live in the `observe_hook` and `eidos` sections of tuneables. The canonical way to change them is via `~/.spark/tuneables.json`:

```json
{
  "observe_hook": { "eidos_enabled": true, "outcome_checkin_enabled": false },
  "eidos": { "safety_guardrails_enabled": true }
}
```

Env vars are available as overrides (highest priority):

| Variable | Key | Default | Description |
|----------|-----|---------|-------------|
| `SPARK_EIDOS_ENABLED` | `observe_hook.eidos_enabled` | `true` | Enable EIDOS integration |
| `SPARK_OUTCOME_CHECKIN` | `observe_hook.outcome_checkin_enabled` | `false` | Enable outcome check-ins |
| `SPARK_OUTCOME_CHECKIN_MIN_S` | `observe_hook.outcome_checkin_min_s` | `1800` | Min seconds between check-ins |

See `docs/CONFIG_AUTHORITY.md` for the full env var reference and precedence model.

---

## CLI Commands

```bash
# Overview
spark eidos

# Statistics
spark eidos --stats

# List episodes
spark eidos --episodes

# List distillations
spark eidos --distillations
spark eidos --distillations --type heuristic

# List policies
spark eidos --policies

# List decision packets
spark eidos --steps
spark eidos --steps --episode <episode_id>

# Intelligence metrics
spark eidos --metrics

# Evidence store stats
spark eidos --evidence

# Deferred validations
spark eidos --deferred

# Migration
spark eidos --migrate --dry-run
spark eidos --migrate
spark eidos --validate-migration
```

---

## Checklist: Are We Following EIDOS?

Use this checklist to verify EIDOS principles are being followed:

### Before Every Action

- [ ] **Prediction made?** Confidence level assigned?
- [ ] **Memory retrieved?** Relevant distillations found?
- [ ] **Memory cited?** Past experience acknowledged?
- [ ] **Phase appropriate?** Action allowed in current phase?
- [ ] **Guardrails checked?** No blocking conditions?

### After Every Action

- [ ] **Outcome recorded?** Result captured (success/failure)?
- [ ] **Prediction evaluated?** Compared to actual outcome?
- [ ] **Surprise calculated?** Was outcome unexpected?
- [ ] **Lesson extracted?** What did we learn?
- [ ] **Evidence captured?** Tool output saved?

### At Episode End

- [ ] **Episode completed?** Outcome assigned?
- [ ] **Distillation run?** Rules extracted?
- [ ] **Metrics updated?** Compounding rate recalculated?
- [ ] **Deferred validations tracked?** Pending items logged?

### Weekly Check

- [ ] **Compounding rate > 40%?**
- [ ] **Reuse rate > 40%?**
- [ ] **Loop suppression < 3?**
- [ ] **Distillation quality > 60%?**
- [ ] **No stale deferred validations?**

---

## Files Reference

| File | Purpose |
|------|---------|
| `lib/eidos/__init__.py` | Package exports |
| `lib/eidos/models.py` | Core data models |
| `lib/eidos/control_plane.py` | Watchers, budget enforcement |
| `lib/eidos/memory_gate.py` | Importance scoring |
| `lib/eidos/distillation_engine.py` | Post-episode reflection |
| `lib/eidos/store.py` | SQLite persistence |
| `lib/eidos/guardrails.py` | Hard gates (Evidence Before Modification) |
| `lib/eidos/evidence_store.py` | Ephemeral audit trail |
| `lib/eidos/escalation.py` | Structured help requests |
| `lib/eidos/validation.py` | Validation methods |
| `lib/eidos/metrics.py` | Intelligence metrics |
| `lib/eidos/migration.py` | Data migration |
| `lib/eidos/integration.py` | Hook integration bridge |
| `hooks/observe.py` | Claude Code hook entry point |

---

## Remember

> **Intelligence compounds when:**
> 1. Every action is a decision packet (not a log)
> 2. Predictions are compared to outcomes
> 3. Lessons are extracted and stored
> 4. Memory is retrieved AND cited
> 5. Rules are enforced, not suggested
>
> **The vertical loop is non-negotiable:**
> Action → Prediction → Outcome → Evaluation → Policy → Distillation → Reuse
