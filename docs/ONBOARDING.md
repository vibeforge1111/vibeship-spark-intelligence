# 🧠 Spark Intelligence — Onboarding Guide

> Legacy note: this document is kept for historical/reference context.
> For current onboarding, use `docs/SPARK_ONBOARDING_COMPLETE.md`.

## For New Users

### What is Spark Intelligence?

Spark Intelligence is a **self-evolution layer** for AI agents. It continuously captures patterns from your coding interactions, distills them through the EIDOS framework, and feeds intelligence back to your agent — making it genuinely smarter over time. Unlike static system prompts, Spark creates a living memory that evolves with you.

It works with **OpenClaw** (or any Claude-based agent) and requires **zero API keys** — just Claude OAuth. Set `SPARK_EMBEDDINGS=0` to keep it completely free beyond your normal Claude usage.

### Quick Start

```bash
# One command to install everything:
git clone https://github.com/vibeforge1111/spark-openclaw-installer.git
cd spark-openclaw-installer

# Windows:
.\install.ps1

# Mac/Linux:
chmod +x install.sh && ./install.sh
```

That's it. The installer handles Python deps, OpenClaw, Claude Code CLI, config files, and starts the services. After install, just **code normally** — Spark learns in the background.

### What to Expect in Your First 24 Hours

| Timeframe | What Happens |
|-----------|-------------|
| **Hour 0-1** | Spark starts capturing your interactions silently |
| **Hour 1-3** | First patterns detected (communication style, preferences) |
| **Hour 3-6** | First advisory generated — your agent starts adapting |
| **Hour 6-12** | Pattern confidence grows, behavior adjustments become visible |
| **Hour 12-24** | EIDOS distillations form — deep understanding of your workflow |

You don't need to do anything special. Just work. Spark watches and learns.

### Understanding the Dashboard

Open **http://localhost:8765** (Spark Pulse) to see:

- **Neural Activity** — Real-time visualization of learning events
- **Learnings Feed** — What Spark has captured from your interactions
- **Pattern Map** — Detected behavioral and preference patterns
- **Advisory Log** — History of advisories sent to your agent
- **EIDOS View** — Deep distillations of your working style

---

## For Power Users

### How the Self-Evolution Loop Works

```
You code with your agent
        ↓
Spark captures interactions (tailer)
        ↓
Pattern detection runs locally (no embeddings needed)
        ↓
Bridge cycle: Claude reviews patterns, creates advisories
        ↓
Advisories written to SPARK_ADVISORY.md
        ↓
Your agent reads advisories and adapts
        ↓
You notice the improvement (or give feedback)
        ↓
Feedback feeds back into the loop
        ↓
Repeat — agent gets smarter each cycle
```

### Giving Feedback

Feedback is how you steer Spark's learning. Use `agent_feedback.py`:

```python
from spark.agent_feedback import record_feedback, rate_advisory

# Tell Spark about a preference
record_feedback("User prefers functional style over OOP")

# Rate an advisory (did it help?)
rate_advisory(advisory_id="adv_2026_0210_001", helpful=True, notes="Nailed it")

# Report a correction
record_feedback("User corrected: use 'const' not 'let' by default", signal="correction")
```

Or use the CLI:
```bash
spark learn "User prefers dark mode in all tools"
spark feedback --advisory adv_001 --helpful true
```

### Writing Custom Chips

Chips are pluggable intelligence modules. Create one in `chips/`:

```python
# chips/my_chip.py
from spark.chips.base import Chip

class MyChip(Chip):
    name = "my_custom_chip"
    
    async def process(self, interaction):
        # Your custom pattern detection logic
        if "deadline" in interaction.text.lower():
            return self.signal("deadline_detected", confidence=0.8)
        return None
```

Register in `config/chips.yaml` and restart sparkd.

### Tuning the System

All configuration flows through **Config Authority** (`lib/config_authority.py`), a 4-layer resolver:
schema defaults → versioned baseline → runtime overrides → env overrides.

See [`docs/CONFIG_AUTHORITY.md`](CONFIG_AUTHORITY.md) for the full architectural contract and [`docs/TUNEABLES_REFERENCE.md`](TUNEABLES_REFERENCE.md) for every tuneable key, type, and range.

Key tuneables to know:

- **`meta_ralph.quality_threshold`** (default 4.5) — Score floor for learning acceptance
- **`advisor.min_rank_score`** (default 0.4) — Minimum fusion score for advisory ranking
- **`advisory_gate.max_emit_per_call`** (default 2) — Max advice items per tool call
- **`advisory_engine.max_ms`** (default 4000) — Advisory engine time budget in ms

### The `advice_action_rate` Metric

This is your key health metric. It measures: **of all advisories generated, what % led to observable behavior change?**

- **>60%**: Excellent — Spark is well-tuned to your needs
- **30-60%**: Good — Some advisories are noise, consider raising thresholds
- **<30%**: Needs tuning — Lower the memory gate or adjust chip weights

Track it on the dashboard or: `spark status --metrics`

---

## For OpenClaw Users

### How Spark Integrates with OpenClaw

```
┌─────────────────────────────────────┐
│           OpenClaw Agent            │
│                                     │
│  Reads: SPARK_CONTEXT.md            │
│         SPARK_ADVISORY.md           │
│         SPARK_NOTIFICATIONS.md      │
│                                     │
│  Writes: memory/*.md, interactions  │
└──────────────┬──────────────────────┘
               │
    ┌──────────┴──────────┐
    │   Spark Tailer      │  ← Watches OpenClaw workspace
    └──────────┬──────────┘
               │
    ┌──────────┴──────────┐
    │   sparkd (:8787)    │  ← Core intelligence engine
    │   Pattern Detection │
    │   EIDOS Framework   │
    └──────────┬──────────┘
               │
    ┌──────────┴──────────┐
    │   Bridge Worker     │  ← Claude reviews patterns
    └──────────┬──────────┘
               │
    ┌──────────┴──────────┐
    │  Spark Pulse (:8765)│  ← Dashboard
    └─────────────────────┘
```

### Workspace Files

| File | Purpose | Who Writes | Who Reads |
|------|---------|-----------|-----------|
| `SPARK_CONTEXT.md` | Current learnings, patterns, EIDOS | Spark | Agent |
| `SPARK_ADVISORY.md` | Active advisories (HIGH/MED/LOW) | Spark | Agent |
| `SPARK_NOTIFICATIONS.md` | System notifications | Spark | Agent |
| `HEARTBEAT.md` | What agent checks each heartbeat | You/Installer | Agent |
| `SOUL.md` | Agent identity and personality | You/Onboard | Agent |
| `IDENTITY.md` | Human + agent metadata | Onboard script | Agent |

### Cron Setup for Advisory Review

Option 1 — **OpenClaw Cron** (recommended):
```bash
openclaw cron add --every 60m --command "python sparkd.py bridge --once --output openclaw"
```

Option 2 — **System crontab**:
```bash
# Run bridge every hour
0 * * * * cd ~/.spark/vibeship-spark-intelligence && SPARK_EMBEDDINGS=0 python3 bridge_worker.py --once
```

Option 3 — **HEARTBEAT.md** (agent-driven):
The default HEARTBEAT.md already includes advisory checking. The agent will read advisories every heartbeat (~30 min).

### HEARTBEAT.md Configuration

The installer sets up HEARTBEAT.md to:
1. Read SPARK_ADVISORY.md for new advisories
2. Read SPARK_NOTIFICATIONS.md for system events
3. Check SPARK_CONTEXT.md for updated learnings
4. Periodically feed observations back to Spark

Edit `~/.openclaw/workspace/HEARTBEAT.md` to customize.

### The `spark` CLI Commands

```bash
spark start              # Start sparkd + bridge + pulse
spark stop               # Stop all services
spark status             # Health check + metrics
spark learn "insight"    # Manually teach Spark something
spark advisory "warning" # Create a manual advisory
spark pattern "pattern"  # Report a detected pattern
spark bridge             # Trigger a bridge cycle manually
spark bridge --once      # Run one cycle and exit
spark logs               # Tail sparkd logs
spark config             # Show current config
```

---

## Why SPARK_EMBEDDINGS=0?

This is **critical** and set by default. Here's why:

1. **Cost**: Embeddings require API calls for every piece of text. Over days of coding, this adds up fast.
2. **Not needed**: Spark's pattern detection uses keyword matching + frequency analysis, which works great without embeddings.
3. **Privacy**: No text leaves your machine for embedding — everything stays local.
4. **Speed**: No network latency for embedding calls.

The only Claude API usage is the bridge cycle (~1 call/hour), which uses your OAuth session.

If you *want* embeddings for advanced semantic matching, set `SPARK_EMBEDDINGS=1` — but understand the cost implications.
