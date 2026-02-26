# EIDOS Quickstart Guide

> **EIDOS** = Explicit Intelligence with Durable Outcomes & Semantics
>
> The self-correcting intelligence system that forces learning through prediction loops, memory binding, and automatic rabbit-hole detection.

Navigation hub: `docs/GLOSSARY.md`

---

## Table of Contents

1. [Quick Start (30 seconds)](#quick-start-30-seconds)
2. [How It Works](#how-it-works)
3. [CLI Commands](#cli-commands)
4. [What to Watch For](#what-to-watch-for)
5. [The 8 Watchers](#the-8-watchers)
6. [Understanding the Phases](#understanding-the-phases)
7. [When Things Go Wrong](#when-things-go-wrong)
8. [Configuration](#configuration)
9. [Troubleshooting](#troubleshooting)

---

## Quick Start (30 seconds)

### 1. EIDOS is Already Running

If you're using Claude Code with Spark hooks configured, EIDOS is **automatically active**.

Check status:
```bash
cd <REPO_ROOT>
python -c "from lib.eidos import get_store; print(get_store().get_stats())"
```

### 2. Verify Hook Integration

```bash
python -c "
from hooks.observe import EIDOS_ENABLED, EIDOS_AVAILABLE
print(f'EIDOS Enabled: {EIDOS_ENABLED}')
print(f'EIDOS Available: {EIDOS_AVAILABLE}')
"
```

Both should be `True`.

### 3. View Current Stats

```bash
python -c "
from lib.eidos import get_store, get_elevated_control_plane
store = get_store()
stats = store.get_stats()
print('=== EIDOS Status ===')
for k, v in stats.items():
    print(f'  {k}: {v}')
"
```

---

## How It Works

### The Vertical Loop

Every tool call goes through:

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                 THE EIDOS VERTICAL LOOP                     â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚                                                             â”‚
â”‚   PreToolUse (hooks/observe.py)                             â”‚
â”‚   â”œâ”€â”€ Make prediction (confidence 0-1)                      â”‚
â”‚   â”œâ”€â”€ Create Step with hypothesis                           â”‚
â”‚   â”œâ”€â”€ Check watchers (8 active)                             â”‚
â”‚   â”œâ”€â”€ Check control plane                                   â”‚
â”‚   â””â”€â”€ BLOCK if any watcher fires                            â”‚
â”‚                                                             â”‚
â”‚   Tool Executes...                                          â”‚
â”‚                                                             â”‚
â”‚   PostToolUse / PostToolUseFailure                          â”‚
â”‚   â”œâ”€â”€ Record result                                         â”‚
â”‚   â”œâ”€â”€ Evaluate prediction vs outcome                        â”‚
â”‚   â”œâ”€â”€ Calculate surprise level                              â”‚
â”‚   â”œâ”€â”€ Extract lesson                                        â”‚
â”‚   â”œâ”€â”€ Score for memory persistence                          â”‚
â”‚   â””â”€â”€ Update phase if needed                                â”‚
â”‚                                                             â”‚
â”‚   SessionEnd                                                â”‚
â”‚   â””â”€â”€ Complete episode â†’ Run distillation                   â”‚
â”‚                                                             â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### Data Flow

```
Claude Code
    â”‚
    â–¼
hooks/observe.py â”€â”€â”€â”€â”€â”€â–º lib/eidos/integration.py
    â”‚                           â”‚
    â”‚                           â–¼
    â”‚                    ElevatedControlPlane
    â”‚                           â”‚
    â”‚              â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
    â”‚              â–¼            â–¼            â–¼
    â”‚         Watchers    StateMachine   EscapeProtocol
    â”‚              â”‚            â”‚            â”‚
    â”‚              â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
    â”‚                           â”‚
    â”‚                           â–¼
    â”‚                    ~/.spark/eidos.db
    â”‚                    (SQLite database)
    â”‚
    â–¼
Continue or BLOCK
```

### Where Data Lives

| File | Purpose |
|------|---------|
| `~/.spark/eidos.db` | SQLite database (episodes, steps, distillations) |
| `~/.spark/truth_ledger.json` | Claims, facts, rules with evidence |
| `~/.spark/policy_patches.json` | Behavior change rules |
| `~/.spark/acceptance_plans.json` | Definition of Done for episodes |
| `~/.spark/eidos_active_episodes.json` | Session â†’ Episode mapping |

---

## CLI Commands

### Quick Status

```bash
# Python one-liner for stats
python -c "from lib.eidos import get_store; import json; print(json.dumps(get_store().get_stats(), indent=2))"
```

### View Episodes

```bash
python -c "
from lib.eidos import get_store
store = get_store()
episodes = store.get_recent_episodes(limit=5)
for ep in episodes:
    print(f'{ep.episode_id[:8]} | {ep.phase.value:12} | {ep.outcome.value:12} | {ep.goal[:40]}')
"
```

### View Steps for an Episode

```bash
python -c "
from lib.eidos import get_store
store = get_store()
# Get most recent episode
episodes = store.get_recent_episodes(limit=1)
if episodes:
    steps = store.get_episode_steps(episodes[0].episode_id)
    for s in steps[-10:]:
        print(f'{s.step_id[:8]} | {s.evaluation.value:8} | {s.action_details.get(\"tool\", \"?\"):10} | {s.intent[:30]}')
"
```

### View Distillations (Learned Rules)

```bash
python -c "
from lib.eidos import get_store
store = get_store()
distillations = store.get_distillations(limit=10)
for d in distillations:
    print(f'{d.type.value:12} | conf={d.confidence:.2f} | {d.statement[:50]}')
"
```

### View Truth Ledger

```bash
python -c "
from lib.eidos import get_truth_ledger
ledger = get_truth_ledger()
stats = ledger.get_stats()
print('Truth Ledger:')
for k, v in stats.items():
    print(f'  {k}: {v}')
"
```

### View Policy Patches

```bash
python -c "
from lib.eidos import get_policy_patch_engine
engine = get_policy_patch_engine()
for patch in engine.patches.values():
    status = 'ON' if patch.enabled else 'OFF'
    print(f'[{status}] {patch.name}: {patch.description[:50]}')
"
```

### Check Watcher Status

```bash
python -c "
from lib.eidos import get_elevated_control_plane
ecp = get_elevated_control_plane()
print('Recent Watcher Alerts:')
for alert in ecp.watcher_engine.alert_history[-10:]:
    print(f'  {alert.watcher.value}: {alert.message[:50]}')
"
```

---

## What to Watch For

### Key Metrics

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| **Success Rate** | > 70% | 50-70% | < 50% |
| **Compounding Rate** | > 40% | 20-40% | < 20% |
| **Avg Steps to Goal** | < 15 | 15-25 | > 25 |
| **Watcher Fires/Session** | 0-2 | 3-5 | > 5 |
| **Escape Protocol Triggers** | 0 | 1 | > 1 |

### Dashboard Script

Use the built-in script at `scripts/eidos_dashboard.py`.

If you want to customize a local variant, start from this template:

```python
#!/usr/bin/env python3
"""EIDOS Dashboard - Quick health check"""

import sys
sys.path.insert(0, '/path/to/vibeship-spark-intelligence')

from lib.eidos import (
    get_store, get_elevated_control_plane,
    get_truth_ledger, get_policy_patch_engine,
    get_minimal_mode_controller
)

def main():
    store = get_store()
    ecp = get_elevated_control_plane()
    ledger = get_truth_ledger()
    patches = get_policy_patch_engine()
    minimal = get_minimal_mode_controller()

    stats = store.get_stats()

    print("=" * 60)
    print("                    EIDOS DASHBOARD")
    print("=" * 60)

    print("\nðŸ“Š DATABASE STATS")
    print(f"   Episodes:      {stats['episodes']}")
    print(f"   Steps:         {stats['steps']}")
    print(f"   Distillations: {stats['distillations']}")
    print(f"   Policies:      {stats['policies']}")
    print(f"   Success Rate:  {stats['success_rate']:.1%}")

    print("\nðŸ” WATCHERS")
    alert_count = len(ecp.watcher_engine.alert_history)
    print(f"   Total Alerts:  {alert_count}")
    if ecp.watcher_engine.alert_history:
        recent = ecp.watcher_engine.alert_history[-3:]
        for a in recent:
            print(f"   â””â”€ {a.watcher.value}: {a.message[:40]}")

    print("\nðŸ“– TRUTH LEDGER")
    tl_stats = ledger.get_stats()
    print(f"   Claims:        {tl_stats['claims']}")
    print(f"   Facts:         {tl_stats['facts']}")
    print(f"   Rules:         {tl_stats['rules']}")
    print(f"   High Conf:     {tl_stats['high_confidence']}")

    print("\nâš™ï¸  POLICY PATCHES")
    patch_stats = patches.get_stats()
    print(f"   Active:        {patch_stats['enabled']}")
    print(f"   Triggered:     {patch_stats['total_triggers']}")
    print(f"   Effectiveness: {patch_stats['effectiveness']:.1%}")

    print("\nðŸ›¡ï¸  MINIMAL MODE")
    mm_stats = minimal.get_stats()
    print(f"   Currently:     {'ACTIVE' if mm_stats['currently_active'] else 'Inactive'}")
    print(f"   Times Used:    {mm_stats['times_entered']}")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
```

Run it:
```bash
python scripts/eidos_dashboard.py
```

---

## The 8 Watchers

| # | Watcher | Trigger | Action | What It Means |
|---|---------|---------|--------|---------------|
| 1 | **Repeat Failure** | Same error 2x | â†’ DIAGNOSE | Stop retrying, investigate |
| 2 | **No New Evidence** | 5 steps without evidence | â†’ DIAGNOSE | Spinning wheels, need data |
| 3 | **Diff Thrash** | Same file 3x | Freeze file | File is not the problem |
| 4 | **Confidence Stagnation** | Delta < 0.05 Ã— 3 | â†’ PLAN | Need new approach |
| 5 | **Memory Bypass** | No citation | BLOCK | Must use past learning |
| 6 | **Budget Half No Progress** | >50%, no progress | â†’ SIMPLIFY | Scope too big |
| 7 | **Scope Creep** | Plan grows, progress doesn't | â†’ SIMPLIFY | Reduce scope 50% |
| 8 | **Validation Gap** | >2 steps without validation | â†’ VALIDATE | Need to verify state |

### When Watchers Fire

You'll see in stderr:
```
[EIDOS] BLOCKED: Error 'Edit:old_string not found' occurred 2 times
[EIDOS] Required: new hypothesis + discriminating test
```

This means EIDOS has detected a rabbit hole and is forcing you to change approach.

---

## Understanding the Phases

```
EXPLORE â”€â”€â–º PLAN â”€â”€â–º EXECUTE â”€â”€â–º VALIDATE â”€â”€â–º CONSOLIDATE
    â–²                              â”‚
    â”‚                              â–¼
    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ DIAGNOSE â—„â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                   â”‚
                   â–¼
                SIMPLIFY
                   â”‚
                   â–¼
            ESCALATE / HALT
```

| Phase | What Happens | Allowed Actions |
|-------|--------------|-----------------|
| **EXPLORE** | Gather context, understand problem | Read, Glob, Grep |
| **PLAN** | Design approach, create acceptance tests | Read, Glob, Grep |
| **EXECUTE** | Do the work | All tools |
| **VALIDATE** | Prove it works | Bash (tests), Read |
| **CONSOLIDATE** | Extract lessons, distill | Read, Write (docs) |
| **DIAGNOSE** | Debug, investigate | Read, Glob, Grep, Bash (read-only) |
| **SIMPLIFY** | Reduce scope, minimal repro | Read, Glob, Grep |
| **ESCALATE** | Ask for help | Read |
| **HALT** | Budget exceeded | None |

---

## When Things Go Wrong

### Escape Protocol Triggered

If you see:
```
[EIDOS] ESCAPE PROTOCOL: Watcher REPEAT_FAILURE triggered twice
```

EIDOS has entered recovery mode. It will:
1. FREEZE actions (no edits)
2. SUMMARIZE what happened
3. ISOLATE smallest failing unit
4. FLIP the question
5. Generate hypotheses
6. Require a discriminating test

### Minimal Mode Activated

If you see:
```
[EIDOS] Entering MINIMAL MODE
```

The smart approach isn't working. Only these actions are allowed:
- Read files
- Search (Glob/Grep)
- Run tests
- Diagnostic commands

To exit: provide new evidence AND new hypothesis.

### Budget Exceeded

If you see:
```
[EIDOS] HALT: Budget exceeded
```

The episode has used all its steps (default: 25) or time (default: 12 minutes).

Check what happened:
```bash
python -c "
from lib.eidos import get_store
store = get_store()
episodes = store.get_recent_episodes(limit=1)
if episodes:
    ep = episodes[0]
    print(f'Goal: {ep.goal}')
    print(f'Steps: {ep.step_count}/{ep.budget.max_steps}')
    print(f'Errors: {ep.error_counts}')
    print(f'Outcome: {ep.outcome.value}')
"
```

---

## Configuration

EIDOS settings are managed through tuneables (`observe_hook` and `eidos` sections). Edit `~/.spark/tuneables.json`:

```json
{
  "observe_hook": {
    "eidos_enabled": true,
    "outcome_checkin_enabled": false,
    "outcome_checkin_min_s": 1800
  },
  "eidos": {
    "max_steps": 25,
    "max_time_seconds": 720,
    "max_retries_per_error": 2,
    "max_file_touches": 3,
    "no_evidence_limit": 5
  }
}
```

Env var overrides (for CI/containers/temporary use):

| Variable | Key | Default |
|----------|-----|---------|
| `SPARK_EIDOS_ENABLED` | `observe_hook.eidos_enabled` | `true` |
| `SPARK_OUTCOME_CHECKIN` | `observe_hook.outcome_checkin_enabled` | `false` |

### Disable EIDOS (if needed)

```bash
# Via env var (temporary)
set SPARK_EIDOS_ENABLED=0
```

Or permanently in `~/.spark/tuneables.json`:
```json
{ "observe_hook": { "eidos_enabled": false } }
```

### Adjust Budgets

Edit budget values in `~/.spark/tuneables.json` under the `eidos` section. Changes are picked up on the next bridge cycle (hot-reload). See `docs/CONFIG_AUTHORITY.md` for the full precedence model.

### Add Custom Policy Patch

```python
from lib.eidos import get_policy_patch_engine, PolicyPatch, PatchTrigger, PatchAction

engine = get_policy_patch_engine()
engine.add_patch(PolicyPatch(
    patch_id="",
    name="My Custom Rule",
    description="When X happens, do Y",
    trigger_type=PatchTrigger.ERROR_COUNT,
    trigger_condition={"threshold": 3},
    action_type=PatchAction.EMIT_WARNING,
    action_params={"message": "Warning: custom condition met"},
))
```

---

## Troubleshooting

### EIDOS Not Running

```bash
# Check if imports work
python -c "from lib.eidos import get_store; print('OK')"

# Check hook integration
python -c "from hooks.observe import EIDOS_AVAILABLE; print(EIDOS_AVAILABLE)"
```

### Database Issues

```bash
# Check database exists
dir %USERPROFILE%\.spark\eidos.db

# View raw stats
python -c "
import sqlite3
conn = sqlite3.connect('<USER_HOME>/.spark/eidos.db')
print('Episodes:', conn.execute('SELECT COUNT(*) FROM episodes').fetchone()[0])
print('Steps:', conn.execute('SELECT COUNT(*) FROM steps').fetchone()[0])
conn.close()
"
```

### Reset EIDOS Data

```bash
# Backup first!
copy %USERPROFILE%\.spark\eidos.db %USERPROFILE%\.spark\eidos.db.backup

# Delete to reset
del %USERPROFILE%\.spark\eidos.db
```

### View Debug Logs

```bash
# Check Spark debug log
type %USERPROFILE%\.spark\debug.log
```

---

## Quick Reference Card

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                    EIDOS QUICK REFERENCE                       â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚                                                                â”‚
â”‚  THE MANTRA:                                                   â”‚
â”‚  "If progress is unclear, stop acting and change the question" â”‚
â”‚                                                                â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚                                                                â”‚
â”‚  5 INVARIANT RULES:                                            â”‚
â”‚  1. No action without falsifiable hypothesis                   â”‚
â”‚  2. Two failures = stop modifying reality                      â”‚
â”‚  3. Progress must be observable                                â”‚
â”‚  4. Budgets are capped (25 steps, 12 min)                      â”‚
â”‚  5. Memory must be consulted                                   â”‚
â”‚                                                                â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚                                                                â”‚
â”‚  WHEN STUCK:                                                   â”‚
â”‚  1. FREEZE (no edits)                                          â”‚
â”‚  2. SUMMARIZE (what we know)                                   â”‚
â”‚  3. ISOLATE (smallest failing unit)                            â”‚
â”‚  4. FLIP (change the question)                                 â”‚
â”‚  5. HYPOTHESIZE (max 3)                                        â”‚
â”‚  6. TEST (1 discriminating test)                               â”‚
â”‚  7. LEARN (create artifact)                                    â”‚
â”‚                                                                â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚                                                                â”‚
â”‚  KEY FILES:                                                    â”‚
â”‚  ~/.spark/eidos.db          - Main database                    â”‚
â”‚  ~/.spark/truth_ledger.json - Claims/facts/rules               â”‚
â”‚  ~/.spark/policy_patches.json - Behavior rules                 â”‚
â”‚                                                                â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

---

## Next Steps

1. **Run the dashboard** to see current state
2. **Watch for watcher alerts** in stderr
3. **Check metrics weekly** for compounding rate
4. **Review distillations** to see what's being learned

EIDOS is designed to be invisible when things are going well, and highly visible when things go wrong. Trust the watchers.


