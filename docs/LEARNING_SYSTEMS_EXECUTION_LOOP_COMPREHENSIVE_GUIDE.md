# Spark Learning Systems — Executive Loop Comprehensive Guide

## Scope and intent

This guide explains how to operate the Spark Learning Systems execution loop safely and intentionally:

- Discover what is broken or weak in Spark intelligence.
- Let the system analyze and propose improvements.
- Run small controlled tests.
- Keep only improvements backed by measurable outcomes.
- Roll back quickly when evidence is negative.
- Preserve safety through hard stop and budget controls.

The control plane for this run loop is in **Spark Learning Systems**.

---

## Service map and addresses

Use these endpoints as the canonical control points:

- `http://localhost:8790` — Executive Loop API (System 26 daemon)
  - Docs: `/docs`
  - Health: `/health`
  - Main control/status endpoints:
    - `GET /status`
    - `GET /plan`
    - `GET /budget`
    - `GET /history`
    - `POST /mode`
    - `POST /pause`
    - `POST /resume`
    - `POST /kill`
    - `POST /override`
- `http://localhost:8780` — Neural Nexus dashboard/API (unified learning systems view)
  - Docs: `/docs` and `/openapi.json`
  - Status: `/health`
  - Dashboard status: `/api/status`
  - Layer summary: `/api/layers`
  - Timeline: `/api/timeline`
  - Run controls:
    - `POST /api/run/{cycle}` (`full`, `competence`, `consciousness`, `growth`, `evolution`, etc. depending on running config)
    - `POST /api/run/system/{number}` (`1` to `26` depending on local install)
- `http://localhost:8787` — Sparkd / MCP daemon health endpoint
  - `/health`
- `http://localhost:8770` — Spark Neural/social intelligence layer
  - Docs: `/docs`
  - Status: `/api/status`
  - Overview: `/api/overview`
  - Learning flow: `/api/learning-flow`
  - Gaps: `/api/gaps`
  - Filter funnel: `/api/filter-funnel`
  - Topics: `/api/topics`
  - Research: `/api/research`
- `http://localhost:8765` — Spark Pulse / connected observability
  - Docs: `/docs`
  - Status: `/api/status`
  - Services: `/api/services`
  - Trace: `/api/trace`
  - Tuneables status: `/api/tuneables/status`
- `http://localhost:8080` — Mind service (memory + patterns)
  - Docs: `/docs`
  - Health: `/health`
  - Stats: `/v1/stats`

---

## Mental model of the loop

Think of execution as a five-step control cycle:

1. **Observe**
   - Query system health and layer health (`/status`, `/layers`, `/health`).
2. **Analyze**
   - Pull current plan and budget context (`/plan`, `/budget`).
3. **Act**
   - Trigger scoped execution (`/api/run/{cycle}` or `/api/run/system/{n}`).
4. **Validate**
   - Read action outcomes from `/history` and layer/state diffs from `/api/layers`.
5. **Decide**
   - Keep results if outcomes improved and stayed safe.
   - Roll back/reverse by pausing and killing further actions if outcomes regressed.

The loop is only useful when bounded by measurable acceptance criteria and explicit stop conditions.

---

## Safety controls and default operating mode

### Hard safety controls (must be available before autonomous operation)

- **Kill switch**: `POST /kill` (immediate stop)
- **Pause/resume**: `POST /pause` and `POST /resume`
- **Mode enforcement**: set explicit mode with `POST /mode`
- **Budget caps**: check `GET /budget` before and during loops
- **Evidence guardrail**: verify traces and status before allowing repeated actions

### Recommended launch posture

- Start with:
  - `autonomous` only when health is coherent and budget is not near cap.
  - `manual` for first remediation wave after config changes.
- Keep `pause`/`kill` as your default abort mechanism.

---

## Pre-flight checks (required every run)

Run these exact checks before doing any changes:

```powershell
curl.exe -s http://localhost:8790/health
curl.exe -s http://localhost:8790/status
curl.exe -s http://localhost:8790/budget
curl.exe -s http://localhost:8790/plan
curl.exe -s http://localhost:8780/health
curl.exe -s http://localhost:8780/api/status
curl.exe -s http://localhost:8780/api/layers
curl.exe -s http://localhost:8765/api/status
curl.exe -s http://localhost:8765/api/services
curl.exe -s http://localhost:8787/health
curl.exe -s http://localhost:8080/v1/stats
```

If any of these are missing/errored, stop and resolve infra before proceeding.

---

## Best-practice execution order for “Spark intelligence and consciousness first”

Use this sequence to specifically address your stated priority (intelligence + advisory quality):

1. **Assess consciousness and intention quality**
   - Review `/api/layers` and identify growth / consciousness critical counts.
   - Review Spark consciousness-facing signals:  
     `curl.exe -s http://localhost:8770/api/overview`
2. **Review advisory quality**
   - `curl.exe -s http://localhost:8765/api/status`
   - `curl.exe -s http://localhost:8765/api/trace?limit=20`
3. **Run focused cycles first**
   - `POST /api/run/growth`
   - `POST /api/run/consciousness`
   - `POST /api/run/evolution`
4. **Open hypothesis stage**
   - `curl.exe -s http://localhost:8790/plan`
   - Confirm high priority signals are valid and actionable.
5. **Validate with evidence**
   - Compare before/after `/api/layers`
   - Check `/history` for failures, test outcomes, and merge/push actions
6. **Stop condition**
   - If repeated test failures or safety issues appear, pause/kill immediately.
   - Resume only after manual correction and budget review.

---

## Execution command reference

### Executive loop controls (`:8790`)

Set mode:

```powershell
curl.exe -X POST http://localhost:8790/mode -H "Content-Type: application/json" -d "{\"mode\":\"manual\",\"reason\":\"targeted growth and consciousness repair\"}"
```

Pause, resume, kill:

```powershell
curl.exe -X POST http://localhost:8790/pause
curl.exe -X POST http://localhost:8790/resume
curl.exe -X POST http://localhost:8790/kill
```

Read current status + plan + history:

```powershell
curl.exe -s http://localhost:8790/status
curl.exe -s http://localhost:8790/plan
curl.exe -s http://localhost:8790/budget
curl.exe -s http://localhost:8790/history?limit=25
```

### Neural Nexus run controls (`:8780`)

Run a whole cycle:

```powershell
curl.exe -X POST http://localhost:8780/api/run/full
```

Run specific layer cycle (examples):

```powershell
curl.exe -X POST http://localhost:8780/api/run/competence
curl.exe -X POST http://localhost:8780/api/run/consciousness
curl.exe -X POST http://localhost:8780/api/run/growth
curl.exe -X POST http://localhost:8780/api/run/evolution
```

Run a single system:

```powershell
curl.exe -X POST http://localhost:8780/api/run/system/21
curl.exe -X POST http://localhost:8780/api/run/system/22
```

Check run state and layer health:

```powershell
curl.exe -s http://localhost:8780/api/run/status
curl.exe -s http://localhost:8780/api/layers
curl.exe -s http://localhost:8780/api/status
curl.exe -s http://localhost:8780/api/timeline
```

### Spark tracer + advisory visibility (`:8765`)

```powershell
curl.exe -s http://localhost:8765/api/status
curl.exe -s http://localhost:8765/api/services
curl.exe -s http://localhost:8765/api/trace?limit=20
curl.exe -s http://localhost:8765/api/tuneables/status
```

### Learning systems bridge (safe write ingress)

Use these commands instead of direct writes to `~/.spark/cognitive_insights.json` or `~/.spark/tuneables.json`:

```powershell
python scripts/learning_systems_bridge.py store-insight `
  --text "Use tighter retrieval threshold for low-context prompts" `
  --category reasoning `
  --source system_04 `
  --context retrieval_gauntlet `
  --confidence 0.74

python scripts/learning_systems_bridge.py propose-tuneable `
  --system-id 04 `
  --section advisor `
  --key min_rank_score `
  --new-value 0.52 `
  --reasoning "Observed precision gain in replay scenarios" `
  --confidence 0.68
```

Bridge artifacts:

- `~/.spark/learning_systems/insight_ingest_audit.jsonl`
- `~/.spark/learning_systems/tuneable_proposals.jsonl`

---

## Analyze → propose → test → keep/rollback protocol (required operating standard)

Use this exact protocol for trustworthy improvements.

### 1) Analyze
- Capture baseline:
  - `:8780/api/layers`
  - `:8790/budget`
  - `:8790/status`
  - `:8765/api/status`
- Record critical/not_run counts and key risk signals.

### 2) Propose
- Read `:8790/plan` and map each signal to a concrete action.
- Proposals should target one layer or one system per action cycle first (no shotgun loops).

### 3) Test
- Run one bounded control action (`/api/run/system/{n}` or one layer cycle).
- Immediately sample `:8790/history?limit=20`.
- Validate branch/test logs for hard errors.

### 4) Measure
- Re-query `/api/layers` and `/api/status`.
- Confirm quality movement on target metrics and advisory outcomes.
- Confirm no budget drift:
  - `merges` should only increase with verified gains
  - `pushes` should remain constrained by cap

### 5) Keep / Rollback
- **Keep**:
  - clear test success,
  - no safety violations,
  - measurable improvement in target metric or stability.
- **Rollback / Stop loop**:
  - `Tests failed on branch` repeats,
  - budget near exhaustion,
  - safety violation risk,
  - advisory output becomes stale/degraded.

Immediate rollback action:

```powershell
curl.exe -X POST http://localhost:8790/pause
curl.exe -X POST http://localhost:8790/kill
```

Then perform root-cause analysis before re-enabling.

---

## Working with Vibeship Optimizer / external optimization layers

When loop output is ready for optimizer integration:

1. Extract evidence:
   - `:8790/history`
   - `:8780/api/layers`
   - `:8765/api/trace`
2. Compare optimizer recommendation against observed outcomes:
   - only apply recommended tuneables when test evidence is positive.
3. Apply only after:
   - budget headroom,
   - no unresolved `not_run` spikes,
   - no repeated branch failures.
4. Keep a rollback checkpoint:
   - revert tuneable changes if metric trend reverses within two cycles.

---

## Failure playbook (high-signal failure modes)

### `Tests failed on branch`
- Action:
  - Pause loop
  - Run single-system execution manually
  - Check output artifacts in the same run context
  - Fix root cause in harness/branch creation path

### Advisory stale
- Action:
  - confirm `/8765/api/status` and `/8765/api/trace`
  - verify spark daemon bridge is online at `8787/health`
  - re-run targeted advisory flow and re-check `/8770` learning flow metrics

### Repeated no-run across many systems
- Action:
  - run a deterministic full-cycle only after fixing gating dependencies
  - avoid letting autonomous loop keep repeating unproductive evolves

---

## Suggested daily operating loop

1. Run pre-flight checks.
2. Set mode manual and cap-limited budget window.
3. Run priority layers one at a time:
   - growth -> consciousness -> evolution -> competence (as needed).
4. Validate and log outcomes.
5. Pause if quality drops or tests fail repeatedly.
6. Resume only with a new explicit target and clean evidence.

---

## Quick command checklist (copy/paste)

```powershell
curl.exe -s http://localhost:8790/status
curl.exe -s http://localhost:8790/plan
curl.exe -s http://localhost:8790/budget
curl.exe -s http://localhost:8790/history?limit=25
curl.exe -s http://localhost:8780/api/layers
curl.exe -s http://localhost:8780/api/status
curl.exe -s http://localhost:8780/api/run/status
curl.exe -s http://localhost:8770/api/overview
curl.exe -s http://localhost:8765/api/services
curl.exe -s http://localhost:8765/api/trace?limit=20
curl.exe -s http://localhost:8787/health
curl.exe -s http://localhost:8080/v1/stats
```

When done, stop the loop if needed:

```powershell
curl.exe -X POST http://localhost:8790/pause
curl.exe -X POST http://localhost:8790/kill
```

---

## Governance notes

- Never let autonomous evolution run without:
  - current status snapshot,
  - clear stop switch,
  - explicit pass/fail measurement criteria.
- Prefer short cycles over broad full loops during stabilization.
- Track changes only if they improve measurable advisory + intelligence behavior.
