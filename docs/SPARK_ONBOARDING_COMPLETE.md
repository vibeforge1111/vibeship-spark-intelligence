# Spark Intelligence — Complete Onboarding Guide

> **One document. Zero fluff. Everything you need from install to first insight.**
>
> Estimated time: 15 minutes to running, 30 minutes to fully configured.

---

## Table of Contents

1. [What Spark Actually Does](#1-what-spark-actually-does)
2. [System Requirements](#2-system-requirements)
3. [Install (3 minutes)](#3-install)
4. [Start Services (1 minute)](#4-start-services)
5. [Verify Everything Works (2 minutes)](#5-verify-everything-works)
6. [Connect Your Coding Agent (5 minutes)](#6-connect-your-coding-agent)
7. [Your First Learning Cycle (5 minutes)](#7-your-first-learning-cycle)
8. [Understanding What Spark Captures](#8-understanding-what-spark-captures)
9. [The Quality Pipeline (How Noise Becomes Wisdom)](#9-the-quality-pipeline)
10. [Observability — Seeing What Spark Knows](#10-observability)
11. [CLI Command Reference (Essential Commands)](#11-cli-command-reference)
12. [Configuration & Tuning](#12-configuration--tuning)
13. [Environment Variables](#13-environment-variables)
14. [File Locations](#14-file-locations)
15. [Troubleshooting](#15-troubleshooting)
16. [Recipes — Common Workflows](#16-recipes)
17. [Architecture at a Glance](#17-architecture-at-a-glance)
18. [Glossary](#18-glossary)
19. [What to Read Next](#19-what-to-read-next)

---

## 1. What Spark Actually Does

Spark Intelligence is a **local AI companion** that learns from your coding sessions and delivers context-aware guidance back to your agent.

The loop:

```
You code → Spark captures events → Pipeline filters noise → Quality gate scores insights
→ Storage → Advisory engine retrieves relevant insights → Delivered pre-tool as guidance
→ Outcomes feed back into the loop → System evolves
```

**What it is not:**
- Not a chatbot. It doesn't talk to you directly.
- Not a static rule set. It evolves from your actual work.
- Not cloud-dependent. Runs 100% on your machine.

**What you get:**
- Pre-tool advisory — Spark surfaces relevant lessons before your agent acts
- Self-correcting quality — bad insights get filtered, good ones get promoted
- Zero-config learning — just code normally, Spark learns in the background
- Domain chips — pluggable expertise modules for specific domains (game dev, fintech, etc.)

---

## 2. System Requirements

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10 or higher |
| **pip** | Included with Python |
| **Git** | Any recent version |
| **OS** | Windows 10+, macOS 12+, or Linux |
| **RAM** | 512 MB minimum for core services |
| **Disk** | ~200 MB for repo + dependencies; `~/.spark/` grows with usage (typically 50-200 MB) |

No API keys required for core functionality. Everything runs locally.
Command style: this guide uses `spark ...`; if `spark` is not on your PATH, use `python -m spark.cli ...`.

---

## 3. Install

### Option A: One-Command Bootstrap (Recommended)

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/vibeforge1111/vibeship-spark-intelligence/main/install.ps1 | iex
```

**Mac / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/vibeforge1111/vibeship-spark-intelligence/main/install.sh | bash
```

This does everything: clone → create virtual environment → install dependencies → start services.
Windows bootstrap includes the health check automatically.
Mac/Linux bootstrap starts services; run `spark health` (or `python -m spark.cli health`) after install.

### Option B: Manual Install (If You Already Cloned)

**Windows:**
```powershell
cd C:\path\to\vibeship-spark-intelligence
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[services]"
```

**Mac / Linux:**
```bash
cd /path/to/vibeship-spark-intelligence
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -e .[services]
```

> **PEP 668 error?** If you see `externally-managed-environment`, make sure you're installing inside the venv (the commands above handle this).

### What Gets Installed

| Component | Purpose |
|-----------|---------|
| `spark` CLI | Command-line interface for all Spark operations |
| `sparkd` | Core daemon API (port 8787) |
| `bridge_worker` | Background event processor |
| `watchdog` | Service health monitor |
| `hooks/observe.py` | Claude Code integration hook |

Dependencies: `fastapi`, `uvicorn`, `httpx`, `pyyaml`, `pydantic` (all installed automatically with `[services]` extras).

---

## 4. Start Services

### Windows
```bat
start_spark.bat
```

Or manually:
```powershell
.\.venv\Scripts\python -m spark.cli up
```

### Mac / Linux
```bash
spark up
# or: python -m spark.cli up
```

### What Starts

| Service | Port | Purpose |
|---------|------|---------|
| **sparkd** | 8787 | Core daemon — event ingestion, advisory engine |
| **bridge_worker** | (no port) | Background processor — runs every 30s |
| **watchdog** | (no port) | Restarts dead services |
| **pulse** | 8765 | Web dashboard (optional, needs `vibeship-spark-pulse` repo) |
| **mind** | 8080 | Memory API (bundled local `mind_server.py`, started by Spark) |

**Lite mode** (core only, skip optional services):
```bash
spark up --lite
```

---

## 5. Verify Everything Works

### Quick Check
```bash
spark health
```

Expected output: green checks for cognitive learner, event queue, and bridge worker.

### Full Status
```bash
spark status
```

Shows: cognitive insights count, queue depth, worker heartbeat, project intelligence, validation stats.

### HTTP Health Checks
```
http://127.0.0.1:8787/health   → "ok" (sparkd)
http://127.0.0.1:8787/status   → JSON system state
```

### Service Status
```bash
spark services
```

Shows running/stale status for each daemon with last heartbeat age.

---

## 6. Connect Your Coding Agent

### Claude Code (Hooks)

Spark integrates with Claude Code through **hooks** — scripts that run before and after every tool call.

**Step 1: Generate hook config**

Windows:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_claude_hooks.ps1
```

Mac / Linux:
```bash
./scripts/install_claude_hooks.sh
```

This creates `~/.claude/spark-hooks.json` with the correct absolute paths.
By default it uses `python`/`python3` from PATH. If you use a project venv, replace the hook command with that venv interpreter path.

**Step 2: Merge into your Claude Code settings**

Open `~/.claude/settings.json` and merge the `hooks` object from `spark-hooks.json` into it.

> Spark intentionally does **not** auto-merge to avoid clobbering your existing hooks.

The hooks config tells Claude Code to run `hooks/observe.py` on three events:
- **PreToolUse** — before any tool runs (Spark makes predictions, emits advisory)
- **PostToolUse** — after success (Spark validates predictions, learns)
- **PostToolUseFailure** — after failure (Spark records errors, detects patterns)

**Step 3: Verify hooks are firing**

After your next Claude Code session, check:
```bash
spark events --limit 5
```

You should see recent events with tool names and types.

**Smoke test** (generates test events without a real session):
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\claude_hook_smoke_test.ps1
```

### Cursor / VS Code

See `docs/cursor.md` — uses `tasks.json` + event emission.

### OpenClaw

See `docs/openclaw/` — uses session JSONL tailing.

---

## 7. Your First Learning Cycle

Once hooks are connected, here's what happens:

### Hour 1: Spark Starts Capturing

Code normally. Every tool call (Read, Edit, Bash, Grep, etc.) generates events. Spark queues them silently.

Check the queue:
```bash
spark events --limit 10
```

### Hour 2-4: Patterns Emerge

The bridge worker processes events every 30 seconds. It extracts:
- **Tool effectiveness** — which tools succeed/fail for you
- **Error patterns** — recurring failures
- **Workflow patterns** — e.g., "Edit without Read" anti-pattern
- **Memory captures** — explicit signals like "remember this" or strong preferences

Check what Spark has learned:
```bash
spark learnings --limit 10
```

### Day 1-2: Insights Get Promoted

High-reliability insights (validated 5+ times, 80%+ reliable) get promoted to your project files:
- `CLAUDE.md` — wisdom, reasoning, context insights
- `AGENTS.md` — meta-learning, self-awareness insights
- `SOUL.md` — communication, user understanding insights

Preview what's ready to promote:
```bash
spark promote --dry-run
```

Actually promote:
```bash
spark promote
```

### Week 1+: Advisory Goes Live

The advisory engine starts surfacing pre-tool guidance:
- Before an Edit: "Last time you edited this file without reading it first"
- Before a Bash command: "This pattern failed 3 times yesterday"
- Context-aware notes based on your validated insights

The system self-tunes: advice that gets followed scores higher, ignored advice scores lower.

---

## 8. Understanding What Spark Captures

### Memory Capture Scoring

Every piece of text gets an **importance score** (0.0 to 1.0):

| Score | Action | Example Triggers |
|-------|--------|-----------------|
| >= 0.65 | Auto-save | "remember this", "non-negotiable", quantitative data |
| 0.55 - 0.65 | Suggest | "I prefer", "design constraint", causal reasoning |
| < 0.55 | Ignore | Generic statements, tool output, noise |

**Signals that boost score:**
- Causal language: "because", "leads to", "results in" (+0.15-0.30)
- Quantitative data: "reduced from 4.2s to 1.6s" (+0.30)
- Technical specificity: naming real tools, libraries, patterns (+0.15-0.30)
- Preferences: "I prefer", "always use", "never do" (+0.55)
- Comparisons: "X is better than Y because..." (+0.15-0.25)

**What gets ignored:**
- Raw tool output
- File listings
- Timing metrics ("Edit took 45ms")
- Generic statements without reasoning

### Insight Categories

| Category | What It Captures | Promoted To |
|----------|-----------------|-------------|
| **Wisdom** | General principles that transcend tools | CLAUDE.md |
| **Reasoning** | Why approaches work, not just that they work | CLAUDE.md |
| **Context** | When patterns apply vs. don't apply | CLAUDE.md, TOOLS.md |
| **Self-Awareness** | Blind spots, struggle patterns | AGENTS.md |
| **Meta-Learning** | How to learn, when to ask vs. act | AGENTS.md |
| **User Understanding** | Your communication preferences, expertise | SOUL.md |
| **Communication** | What explanations work for you | SOUL.md |
| **Creativity** | Novel problem-solving approaches | (not promoted) |

---

## 9. The Quality Pipeline

Every observation goes through multiple quality gates before it becomes trusted knowledge:

```
Event Captured
  ↓
Importance Scoring (memory_capture.py)
  ↓  Score >= 0.55 passes
Quality Gate — Meta-Ralph (meta_ralph.py)
  ↓  Score >= 4/12 passes (QUALITY verdict)
  ↓  Score 2-4 = NEEDS_WORK (may be refined later)
  ↓  Score < 2 = PRIMITIVE (discarded)
Cognitive Storage (cognitive_learner.py)
  ↓  Deduplicated, categorized, stored
Validation Loop
  ↓  Outcomes confirm or contradict insights
  ↓  times_validated and times_contradicted tracked
Promotion Decision
  ↓  Track 1: reliability >= 80% AND validated >= 5 times
  ↓  Track 2: confidence >= 95% AND age >= 6 hours AND validated >= 5
Project File Promotion (CLAUDE.md, AGENTS.md, etc.)
```

### Meta-Ralph Scoring Dimensions

| Dimension | 0 | 1 | 2 |
|-----------|---|---|---|
| **Actionability** | Can't act on it | Vague action | Specific action |
| **Novelty** | Obvious | Somewhat new | Genuine insight |
| **Reasoning** | No "why" | Implied | Explicit causal |
| **Specificity** | Generic | Domain-specific | Context-specific |
| **Outcome-Linked** | No outcome | Implied | Validated outcome |

Total range: 0-12. Threshold: 4.5 (tunable via `meta_ralph.quality_threshold` in `~/.spark/tuneables.json`).

---

## 10. Observability

### Option 1: CLI (Always Available)

```bash
spark status          # Full system snapshot
spark learnings       # What Spark has learned
spark events          # Recent captured events
spark eidos --stats   # Episode/distillation stats
spark services        # Daemon health
```

### Option 2: Obsidian Observatory (Rich Visual Experience)

Generates ~465 markdown pages from your live data.

**Setup:**
1. Install [Obsidian](https://obsidian.md) (free)
2. Generate the vault:
   ```bash
   python scripts/generate_observatory.py --force --verbose
   ```
3. Open in Obsidian: File > Open vault > Select `Spark-Intelligence-Observatory`

**Key pages:**
- `flow.md` — pipeline dashboard with Mermaid diagram
- `stages/` — 12 stage detail pages
- `explore/` — browse individual insights, episodes, verdicts
- `Dashboard.md` — live Dataview queries

Auto-syncs every 120 seconds while Spark is running.

### Option 3: Spark Pulse (Web Dashboard)

Requires `vibeship-spark-pulse` cloned alongside the main repo.

```
http://localhost:8765
```

---

## 11. CLI Command Reference

### Service Management
| Command | What It Does |
|---------|-------------|
| `spark up` | Start all services |
| `spark up --lite` | Start core only (no pulse/mind/watchdog) |
| `spark down` | Stop all services |
| `spark services` | Show daemon health |
| `spark health` | Quick diagnostic |
| `spark ensure` | Start only missing services |

### Learning & Knowledge
| Command | What It Does |
|---------|-------------|
| `spark learnings [--limit N]` | View recent cognitive insights |
| `spark learn CATEGORY "insight text"` | Manually add an insight |
| `spark promote [--dry-run]` | Promote high-value insights to project files |
| `spark write` | Write learnings to markdown |
| `spark sync` | Sync insights to Mind service |
| `spark importance --text "some text"` | Test importance scoring on text |

### Advisory
| Command | What It Does |
|---------|-------------|
| `spark advisory setup` | Interactive 2-question configuration |
| `spark advisory show` | Current advisory preferences |
| `spark advisory doctor` | Diagnostic with recommendations |
| `spark advisory on/off` | Quick toggle |

### Validation & Outcomes
| Command | What It Does |
|---------|-------------|
| `spark validate` | Run validation scan on recent events |
| `spark outcome --result yes/no` | Record explicit outcome |
| `spark outcome-stats` | Show outcome coverage |
| `spark eval` | Evaluate prediction accuracy |

### Project Intelligence
| Command | What It Does |
|---------|-------------|
| `spark project init --domain DOMAIN` | Initialize project profile |
| `spark project status` | Show project summary |
| `spark project questions` | Show suggested questions |
| `spark project capture --type TYPE --text "..."` | Capture project intelligence |

### EIDOS (Episodic Intelligence)
| Command | What It Does |
|---------|-------------|
| `spark eidos --stats` | Episode/distillation statistics |
| `spark eidos --episodes` | List recent episodes |
| `spark eidos --distillations` | List extracted rules |
| `spark eidos --metrics` | Compounding rate metrics |

### Domain Chips
| Command | What It Does |
|---------|-------------|
| `spark chips list` | List installed chips |
| `spark chips status [CHIP_ID]` | Chip health and stats |
| `spark chips insights CHIP_ID` | View chip-specific insights |

### Maintenance
| Command | What It Does |
|---------|-------------|
| `spark events [--limit N]` | View recent queue events |
| `spark process [--drain]` | Run bridge worker manually |
| `spark decay [--apply]` | Prune stale insights |
| `spark sync-context` | Refresh context files |

---

## 12. Configuration & Tuning

All configuration lives in one file: `~/.spark/tuneables.json`

A version-controlled template is at `config/tuneables.json` in the repo.

**Hot-reloadable** — changes take effect within one bridge cycle (30-60 seconds) without restarting services.

### Key Sections

| Section | Controls | Key Parameters |
|---------|----------|----------------|
| `values` | Core pipeline | `queue_batch_size`, `confidence_threshold` |
| `meta_ralph` | Quality gate | `quality_threshold` (default: 3.8) |
| `advisor` | Advisory retrieval | `min_rank_score`, `max_advice_items` |
| `advisory_gate` | Advisory delivery | `max_emit_per_call` (2), `tool_cooldown_s` (15) |
| `advisory_engine` | Advisory orchestration | `max_ms` (4000), `delivery_stale_s` (600) |
| `promotion` | File promotion | Budget caps per file (CLAUDE.md: 40, AGENTS.md: 30) |
| `eidos` | Episodic intelligence | `max_time_seconds`, `max_retries_per_error` |
| `observatory` | Obsidian sync | `vault_dir`, `sync_cooldown_s` |
| `auto_tuner` | Self-evolution | `mode` (apply/observe), `source_boosts` |

### Common Tuning Recipes

**Want more advice?**
```json
{
  "advisory_gate": {
    "max_emit_per_call": 3,
    "tool_cooldown_s": 8
  }
}
```

**Want less advice?**
```json
{
  "advisory_gate": {
    "max_emit_per_call": 1,
    "tool_cooldown_s": 30
  }
}
```

**Want stricter quality?**
```json
{
  "meta_ralph": {
    "quality_threshold": 5.0
  }
}
```

**Want more permissive capture?**
```json
{
  "memory_capture": {
    "auto_save_threshold": 0.50
  }
}
```

---

## 13. Environment Variables

### Ports (Override Defaults)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SPARKD_PORT` | 8787 | Core daemon |
| `SPARK_PULSE_PORT` | 8765 | Web dashboard |
| `SPARK_MIND_PORT` | 8080 | Memory API |

### Startup Behavior

| Variable | Default | Purpose |
|----------|---------|---------|
| `SPARK_LITE` | (unset) | Set to `1` for core-only mode |
| `SPARK_NO_MIND` | (unset) | Set to `1` to skip Mind service |
| `SPARK_NO_PULSE` | (unset) | Set to `1` to skip Pulse dashboard |
| `SPARK_NO_WATCHDOG` | (unset) | Set to `1` to skip watchdog |

### Advisory Control

| Variable | Default | Purpose |
|----------|---------|---------|
| `SPARK_ADVISORY_ENGINE` | `1` | Enable/disable advisory engine |
| `SPARK_ADVISORY_MAX_MS` | `4000` | Advisory timeout (ms) |
| `SPARK_ADVISORY_EMIT` | `1` | Enable/disable advisory emission |

### Authentication

| Variable | Default | Purpose |
|----------|---------|---------|
| `SPARKD_TOKEN` | (auto from `~/.spark/sparkd.token`) | Auth token for sparkd |

---

## 14. File Locations

### Repo Files (Version Controlled)

```
vibeship-spark-intelligence/
├── spark/cli.py              # CLI (3000+ lines, 50+ commands)
├── hooks/observe.py          # Claude Code hook
├── lib/                      # Core modules (100+ files)
│   ├── meta_ralph.py         # Quality gate
│   ├── cognitive_learner.py  # Insight storage
│   ├── advisor.py            # Advisory retrieval
│   ├── advisory_engine.py    # Advisory orchestration
│   ├── advisory_gate.py      # Emission control
│   ├── promoter.py           # Promotion to project files
│   ├── bridge_cycle.py       # Background processor
│   ├── pipeline.py           # Event processing
│   ├── memory_capture.py     # Importance scoring
│   ├── queue.py              # Event queue
│   ├── eidos/                # Episodic intelligence
│   ├── chips/                # Domain modules
│   └── observatory/          # Obsidian vault generator
├── config/tuneables.json     # Version-controlled config template
├── scripts/                  # Setup and maintenance scripts
├── install.ps1               # Windows bootstrap
├── install.sh                # Mac/Linux bootstrap
└── start_spark.bat           # Windows launcher
```

### User State (`~/.spark/`)

```
~/.spark/
├── tuneables.json            # Runtime configuration (hot-reloadable)
├── cognitive_insights.json   # Learned insights
├── eidos.db                  # SQLite: episodes, steps, distillations
├── sparkd.token              # Auth token
├── queue/
│   └── events.jsonl          # Event queue
├── pids/                     # Service PID files
├── logs/                     # Service log files
├── chip_insights/            # Domain-specific learning
├── advisory_state.json       # Advisory system state
└── cooldowns.json            # Advisory cooldown tracking
```

### Hook Config (`~/.claude/`)

```
~/.claude/
├── settings.json             # Claude Code settings (you edit this)
└── spark-hooks.json          # Generated hook config (merge into settings.json)
```

---

## 15. Troubleshooting

### Spark Won't Start

| Symptom | Fix |
|---------|-----|
| `Port 8787 already in use` | Another sparkd running. `spark down` first, or change `SPARKD_PORT` |
| `Python not found` | Install Python 3.10+. Windows: `winget install Python.Python.3.12` |
| `externally-managed-environment` | Install inside venv: `python -m venv .venv` then activate |
| Services show STALE | `spark down && spark up` to restart cleanly |

### Hooks Not Firing

| Symptom | Fix |
|---------|-----|
| `spark events` shows 0 | Check `~/.claude/settings.json` has hooks merged |
| Events appear but no learnings | Bridge worker may be down. Check `spark services` |
| Hook errors in Claude Code | Check path in settings.json is absolute and correct |

### No Learnings Appearing

| Symptom | Fix |
|---------|-----|
| Events captured but 0 learnings | Normal for first ~50 events. Spark needs data to detect patterns |
| Learnings created but 0 promoted | Promotion needs 5+ validations at 80% reliability. Give it time |
| `spark learnings` empty after days | Check `spark health` — cognitive store may be locked. Delete `~/.spark/.cognitive.lock` if stale |

### Advisory Not Working

| Symptom | Fix |
|---------|-----|
| No pre-tool advice showing | Check `spark advisory show` — may be off. Run `spark advisory on` |
| Advice is stale/irrelevant | Run `spark advisory doctor` for diagnostics |
| Too much advice | Increase cooldowns in tuneables: `advisory_gate.tool_cooldown_s` |

### General Recovery

```bash
# Nuclear restart
spark down
spark up

# Check everything
spark health
spark services
spark status

# Force process pending events
spark process --drain
```

---

## 16. Recipes

### Recipe: "Tell Spark Something Important"

Just say it in your coding session — Spark captures from your prompts:

> "Remember: always use `--no-cache` when building Docker images in this project"

Or use the CLI:
```bash
spark learn wisdom "Always use --no-cache for Docker builds in this project" --context "Docker CI pipeline"
```

### Recipe: "Check What Spark Learned Today"

```bash
spark learnings --limit 20
```

### Recipe: "Preview and Promote Insights"

```bash
# See what's ready
spark promote --dry-run

# Promote to CLAUDE.md, AGENTS.md, etc.
spark promote
```

### Recipe: "Initialize a New Project"

```bash
spark project init --domain engineering --project /path/to/project
spark project questions --project /path/to/project
# Answer the suggested questions to help Spark understand your project
spark project answer eng_arch --project /path/to/project --text "We're building a REST API for user management"
```

### Recipe: "Debug Why Advice Isn't Showing"

```bash
spark advisory doctor --json
# Check: advisory_on, runtime_up, replay_on
# Follow the recommendations
```

### Recipe: "Score Some Text for Importance"

```bash
spark importance --text "We switched from REST to GraphQL because query flexibility reduced frontend round-trips by 60%"
# Shows the importance score and which signals triggered
```

### Recipe: "See EIDOS Distillations (Extracted Rules)"

```bash
spark eidos --distillations
# Shows: heuristics, sharp edges, anti-patterns, playbooks, policies
```

### Recipe: "Set Up Obsidian Observatory"

```bash
# Generate vault
python scripts/generate_observatory.py --force --verbose

# Open in Obsidian: File > Open vault > Select Spark-Intelligence-Observatory
# Start from flow.md — drill down into stages and explorer
```

### Recipe: "Tune Advisory Frequency"

Edit `~/.spark/tuneables.json`:
```json
{
  "advisory_gate": {
    "max_emit_per_call": 2,
    "tool_cooldown_s": 15,
    "advice_repeat_cooldown_s": 300
  }
}
```
Changes take effect within 60 seconds (hot-reload).

### Recipe: "Clean Up Stale Data"

```bash
# Preview what would be removed
spark decay --max-age-days 90

# Actually remove
spark decay --max-age-days 90 --apply
```

---

## 17. Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────┐
│  YOUR CODING AGENT (Claude Code / Cursor / OpenClaw)        │
│  Every tool call fires hooks/observe.py                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ PreToolUse / PostToolUse / PostToolUseFailure
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  EVENT QUEUE (~/.spark/queue/events.jsonl)                   │
│  File-based, lock-free overflow, auto-rotation at 10MB      │
└──────────────────────┬──────────────────────────────────────┘
                       │ bridge_worker processes every 30s
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  PROCESSING PIPELINE (lib/pipeline.py)                      │
│  ├─ Priority classification (prompts & failures first)      │
│  ├─ Pattern detection (tool effectiveness, error patterns)  │
│  ├─ Session workflow analysis (anti-pattern detection)      │
│  └─ Micro-insight extraction                                │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  QUALITY GATE — META-RALPH (lib/meta_ralph.py)              │
│  Scores 0-12 on: actionability, novelty, reasoning,         │
│  specificity, outcome linkage                               │
│  >= 4 = QUALITY │ 2-4 = NEEDS_WORK │ < 2 = PRIMITIVE       │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  COGNITIVE STORAGE (lib/cognitive_learner.py)                │
│  8 categories, deduplication, reliability tracking           │
│  Validation loop: confirmed insights gain reliability       │
│  Contradicted insights lose reliability                     │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌──────────────────────┴──────────────────────────────────────┐
│  PROMOTION (lib/promoter.py)      │  ADVISORY (lib/advisor) │
│  reliability >= 80% + 5 vals      │  7 retrieval sources     │
│  → CLAUDE.md, AGENTS.md, etc.     │  Ranked by fusion score  │
│                                    │  Gated by authority +    │
│                                    │  cooldown + dedupe       │
│                                    │  → Pre-tool guidance     │
└────────────────────────────────────┴────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  OUTCOME TRACKING & SELF-EVOLUTION                          │
│  Did the advice help? Auto-tuner adjusts source weights.    │
│  Feedback loop: effective sources get boosted.              │
└─────────────────────────────────────────────────────────────┘
```

### Advisory Sources (Ranked)

| Source | What It Provides | Effectiveness |
|--------|-----------------|---------------|
| **Cognitive** | Validated insights from your sessions | ~62% (dominant) |
| **EIDOS** | Pattern distillations (heuristics, sharp edges) | ~5% |
| **Semantic** | BM25 + embedding hybrid retrieval | ~3% |
| **Bank** | User memory banks | ~10% |
| **Baseline** | Static rules | ~5% |
| **Trigger** | Event-specific rules | ~5% |

### Advisory Authority Levels

| Level | Score Range | Behavior |
|-------|------------|----------|
| **BLOCK** | 0.95+ | EIDOS blocks the action |
| **WARNING** | 0.80-0.95 | Prominent caution header |
| **NOTE** | 0.48-0.80 | Included in context |
| **WHISPER** | 0.30-0.48 | Available if asked |
| **SILENT** | < 0.30 | Logged only |

---

## 18. Glossary

| Term | Definition |
|------|-----------|
| **Advisory** | Pre-tool guidance Spark surfaces to your agent |
| **Bridge Cycle** | One processing pass of the background worker |
| **Chip** | Domain-specific learning module (YAML-defined) |
| **Cognitive Insight** | A stored learning with category, reliability, and evidence |
| **Distillation** | A rule extracted from EIDOS episodes (heuristic, sharp edge, etc.) |
| **EIDOS** | Episodic intelligence system: prediction → outcome → evaluation |
| **Episode** | A bounded learning unit in EIDOS with goals and budget |
| **Fusion Score** | Combined relevance score from multiple retrieval sources |
| **Meta-Ralph** | The quality gate that scores insights 0-12 |
| **Observatory** | Obsidian vault generated from live system data |
| **Promotion** | Moving a validated insight into CLAUDE.md/AGENTS.md/etc. |
| **Pulse** | Web-based analytics dashboard |
| **Reliability** | weighted_validations / (weighted_validations + contradictions) |
| **sparkd** | The core daemon API running on port 8787 |
| **Step** | A single decision in EIDOS: prediction → action → outcome |
| **Tuneables** | Hot-reloadable configuration parameters |

---

## 19. What to Read Next

**Your situation → What to read:**

| Goal | Read |
|------|------|
| Understand the full architecture | `Intelligence_Flow.md` |
| Deep dive on quality gating | `docs/META_RALPH.md` |
| Deep dive on EIDOS | `docs/EIDOS_GUIDE.md` |
| Understand the learning philosophy | `SPARK_LEARNING_GUIDE.md` |
| Full CLI reference | `docs/QUICKSTART.md` section 6 |
| Configure Obsidian Observatory | `docs/OBSIDIAN_OBSERVATORY_GUIDE.md` |
| All tuneables reference | `docs/TUNEABLES_REFERENCE.md` |
| Security model | `docs/security/THREAT_MODEL.md` |
| Contributing | `CONTRIBUTING.md` |
| Full docs index | `docs/DOCS_INDEX.md` |

---

*Built by [Vibeship](https://vibeship.com) — MIT Licensed*
