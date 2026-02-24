# Spark Quick Start Guide

Runtime and operations reference for an already-installed Spark setup.

If this is your first time:
- Canonical onboarding: `docs/SPARK_ONBOARDING_COMPLETE.md`
- Fast onboarding path: `docs/GETTING_STARTED_5_MIN.md`

For the full active documentation map, see `docs/DOCS_INDEX.md`.
For term-based navigation, see `docs/GLOSSARY.md`.
Command style: this guide uses explicit interpreter commands (`python -m spark.cli ...`) for portability.

## First-Time Setup (Do Once)

Use `docs/GETTING_STARTED_5_MIN.md` for install/start/health.
For full context and troubleshooting depth, use `docs/SPARK_ONBOARDING_COMPLETE.md`.

After first successful health check, return to this guide for runtime operations.

## Runtime Operations

### Check Status

```bash
python -m spark.cli status
```

### Start Background Services (Recommended)

These keep the bridge worker running and the dashboard live.

```bash
python -m spark.cli up
# or: spark up
```
Lightweight mode (core services only: sparkd + bridge_worker):
```bash
python -m spark.cli up --lite
```

Repo shortcuts:
```bash
./scripts/run_local.sh
```

Windows (repo):
```bat
start_spark.bat
```
Preferred launch paths on Windows are `start_spark.bat` and `python -m spark.cli ...`.
`scripts/spark.ps1` and `scripts/spark.cmd` are deprecated compatibility wrappers.
By default this starts built-in Mind on `SPARK_MIND_PORT` (default `8080`).
Set `SPARK_NO_MIND=1` to skip Mind startup.
Set `SPARK_LITE=1` to skip dashboards/pulse/watchdog (core services only).
Set `SPARK_NO_PULSE=1` or `SPARK_NO_WATCHDOG=1` for targeted disables.
Spark auto-detects sibling `../vibeship-spark-pulse`. Set `SPARK_PULSE_DIR` env var if it's elsewhere.
Set `SPARK_PULSE_DIR` to override auto-detection.
For this setup, use:
```bat
set SPARK_PULSE_DIR=<SPARK_PULSE_DIR>
```

Check status:
```bash
python -m spark.cli services
# or: spark services
```

### Opportunity Scanner Runtime Checks

Verify scanner status and recent self-Socratic prompts:

```bash
python -c "from lib.opportunity_scanner import get_scanner_status, get_recent_self_opportunities; import json; print(json.dumps(get_scanner_status(), indent=2)); print(json.dumps(get_recent_self_opportunities(limit=5), indent=2))"
```

Inbox workflow (accept/dismiss):
```bash
python -m spark.cli opportunities list --limit 20
python -m spark.cli opportunities accept <id-prefix>
python -m spark.cli opportunities dismiss <id-prefix>
```

Enable Minimax-backed scanner synthesis (optional):

```bash
set SPARK_OPPORTUNITY_LLM_ENABLED=1
set SPARK_OPPORTUNITY_LLM_PROVIDER=minimax
set MINIMAX_API_KEY=your_key_here
set SPARK_MINIMAX_MODEL=MiniMax-M2.5

# Recommended cadence: one LLM "deep scan" at most every 15 minutes per session while you're actively working.
# (Scanner already skips LLM calls when context is insufficient.)
set SPARK_OPPORTUNITY_LLM_COOLDOWN_S=900
```

After setting env vars, restart services (`spark down` then `spark up`) and check scanner heartbeat `llm` fields (`used`, `provider`, `error`).

Verify scanner stats are present in bridge heartbeat:

```bash
python -c "import json; from pathlib import Path; p=Path.home()/'.spark'/'bridge_worker_heartbeat.json'; d=json.loads(p.read_text(encoding='utf-8')); print(json.dumps((d.get('stats') or {}).get('opportunity_scanner') or {}, indent=2))"
```

Inspect persisted scanner artifacts:

```bash
# self-opportunities
python -c "from pathlib import Path; p=Path.home()/'.spark'/'opportunity_scanner'/'self_opportunities.jsonl'; print(p, 'exists=', p.exists())"

# acted outcomes + promotion candidates
python -c "from pathlib import Path; base=Path.home()/'.spark'/'opportunity_scanner'; print((base/'outcomes.jsonl').exists(), (base/'promoted_opportunities.jsonl').exists())"
```

The watchdog auto-restarts workers and warns when the queue grows. Set
`SPARK_NO_WATCHDOG=1` to disable it when using the launch scripts.

Stop services:
```bash
python -m spark.cli down
# or: spark down
```

### Observability

Spark observability is provided by three systems:

- **Spark Pulse** (primary web dashboard): http://localhost:${SPARK_PULSE_PORT:-8765}
  - Tabs/surfaces include Mission, Learning, Rabbit, Acceptance, Ops, Chips, Tuneables, Tools, and Trace/Run drilldowns.
- **Obsidian Observatory** (file-based pipeline viewer): `python scripts/generate_observatory.py --force`
  - Full 12-stage pipeline visualization, explorer pages for every data store, auto-syncs every 120s.
- **CLI scripts**: `scripts/spark_dashboard.py`, `scripts/eidos_dashboard.py`

Port overrides:
- `SPARKD_PORT`
- `SPARK_PULSE_PORT`
- `SPARK_MIND_PORT`

Tip: `spark up` starts core services + Pulse by default. Use `--no-pulse` for debugging.
Tip: `spark up --lite` skips Pulse and watchdog to reduce background load.

### Production Hardening Defaults

- `sparkd` auth: all mutating `POST` endpoints require `Authorization: Bearer <token>` (token auto-resolves from `SPARKD_TOKEN` or `~/.spark/sparkd.token`).
- Queue safety: queue rotation and processed-event consumption both use temp-file + atomic replace.
- Validation loop: bridge cycle runs both prompt validation and outcome-linked validation each cycle.
- Service startup: if Spark Pulse app is unavailable, core services still start and pulse is reported unavailable.

Test gates before push:
```bash
python -m ruff check . --select E9,F63,F7,F82
python -m pytest -q
```

### Automated Always-On (Quick Start)

Keep Spark running at login so hooks never miss events.

#### Windows (Task Scheduler)
Manual setup:
1) Open Task Scheduler -> Create Task
2) Trigger: At log on
3) Action: Start a program
   - Program/script: `spark` (or full `python.exe`)
   - Add arguments: `up --sync-context --project "C:\path\to\your\project"`
   - Start in: `C:\path\to\your\project`

Helper script (creates the task automatically):
```powershell
./scripts/install_autostart_windows.ps1
```

Remove the task:
```powershell
./scripts/remove_autostart_windows.ps1
```

If you get "Access is denied", run PowerShell as Administrator.

#### macOS (launchd)
Create `~/Library/LaunchAgents/co.vibeship.spark.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>co.vibeship.spark</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/python3</string>
      <string>-m</string>
      <string>spark.cli</string>
      <string>up</string>
      <string>--sync-context</string>
      <string>--project</string>
      <string>/path/to/your/project</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$HOME/.spark/logs/launchd.out</string>
    <key>StandardErrorPath</key><string>$HOME/.spark/logs/launchd.err</string>
  </dict>
</plist>
```

Load it:
```bash
launchctl load -w ~/Library/LaunchAgents/co.vibeship.spark.plist
```

Unload it:
```bash
launchctl unload ~/Library/LaunchAgents/co.vibeship.spark.plist
```

#### Linux (systemd user service)
Create `~/.config/systemd/user/spark-up.service`:
```ini
[Unit]
Description=Spark background services

[Service]
Type=simple
ExecStart=python -m spark.cli up --sync-context --project /path/to/your/project
Restart=on-failure

[Install]
WantedBy=default.target
```

Enable and start:
```bash
systemctl --user daemon-reload
systemctl --user enable --now spark-up.service
```

Stop:
```bash
systemctl --user disable --now spark-up.service
```

#### Fallback (cron)
If you prefer cron:
```
@reboot python -m spark.cli up --sync-context --project /path/to/your/project >/dev/null 2>&1
```

### Per-Project Ensure (Optional)

If you want each project to guarantee Spark is running, add this to your
project start script or editor task:

```bash
spark ensure --sync-context --project .
# or: python -m spark.cli ensure --sync-context --project .
```

Windows helper (run from project root):
```bat
scripts\ensure_spark.bat
```

macOS/Linux helper:
```bash
spark ensure --sync-context --project "$(pwd)"
```

### Create Learnings (Programmatic)

```python
from lib.cognitive_learner import get_cognitive_learner

cognitive = get_cognitive_learner()

# Learn from a failure
cognitive.learn_struggle_area(
    task_type="regex_patterns",
    failure_reason="Edge cases in complex patterns"
)

# Learn a principle
cognitive.learn_principle(
    principle="Always test edge cases",
    examples=["Empty input", "Null values", "Unicode"]
)
```

### Write to Markdown

```bash
python -m spark.cli write
# Creates .learnings/LEARNINGS.md
```

### Optional: Agent Context Injection (Opt-in)

If you spawn sub-agents, you can prepend a compact Spark context block to their
prompts. This is off by default.

```bash
SPARK_AGENT_INJECT=1
SPARK_AGENT_CONTEXT_LIMIT=3
SPARK_AGENT_CONTEXT_MAX_CHARS=1200
```

Use `lib.orchestration.inject_agent_context(prompt)` when preparing sub-agent prompts.

## Optional: Scheduled Sync Backup

If you want a safety net (for sessions launched outside wrappers), run sync on a timer.

**Windows Task Scheduler**
- Action: `spark`
- Args: `sync-context`
- Start in: your repo root
- Trigger: every 10-30 minutes

**macOS/Linux (cron)**
```
*/20 * * * * cd /path/to/vibeship-spark-intelligence && spark sync-context >/dev/null 2>&1
```

### Promote High-Value Insights

```bash
# Check what's ready
python -m spark.cli promote --dry-run

# Actually promote
python -m spark.cli promote
# Creates/updates AGENTS.md, CLAUDE.md, etc.
```

## Mind Integration (Optional)

Spark ships with a built-in Mind server (`mind_server.py`) started by `spark up`.
Use this section only if you need explicit checks or want an external Mind runtime.

```bash
# Check built-in Mind health
curl http://127.0.0.1:${SPARK_MIND_PORT:-8080}/health

# Optional: external Mind runtime (if you use it)
# pip install vibeship-mind
# python3 -m mind.lite_tier

# Sync Spark learnings to Mind
python -m spark.cli sync
```

## Semantic Retrieval (Optional)

Enable semantic matching for cognitive insights:

```bash
# Optional: local embeddings
pip install fastembed

# Enable semantic + triggers
# ~/.spark/tuneables.json
#
# "semantic": { "enabled": true, ... }
# "triggers": { "enabled": true, ... }

# Backfill semantic index
python -m spark.index_embeddings --all
# (legacy) python scripts/semantic_reindex.py
```

Use it during real work:
```python
from lib.advisor import advise_on_tool
advice = advise_on_tool("Edit", {"file_path": "src/auth/login.py"}, "edit auth login flow")
```

Semantic retrieval logs and metrics:
- `~/.spark/logs/semantic_retrieval.jsonl`
- `~/.spark/advisor/metrics.json`

## Configuring Tuneables

Tuneables control every runtime behavior — quality thresholds, advisory timing, gate limits, retrieval weights, and more.
231 keys across 31 sections, all configurable without code changes.

For the full key reference, see [`docs/TUNEABLES_REFERENCE.md`](TUNEABLES_REFERENCE.md).
For the architectural contract, see [`docs/CONFIG_AUTHORITY.md`](CONFIG_AUTHORITY.md).

### How to Change a Tuneable

**Option A: Edit the runtime file** (most common)

```json
// ~/.spark/tuneables.json
{
  "advisory_gate": {
    "max_emit_per_call": 3,
    "tool_cooldown_s": 20
  },
  "meta_ralph": {
    "quality_threshold": 5.0
  }
}
```

Save the file. Changes take effect automatically within 1-30 seconds (next bridge cycle).

**Option B: Environment variables** (for CI, containers, or quick overrides)

```bash
# Windows
set SPARK_ADVISORY_MAX_MS=10000
set SPARK_ADVISORY_EMIT_WHISPERS=false

# Mac/Linux
export SPARK_ADVISORY_MAX_MS=10000
export SPARK_ADVISORY_EMIT_WHISPERS=false
```

Env vars override everything — they win over both files. Must be set **before** starting Spark.
Only ~43 keys have env overrides wired. See [`docs/CONFIG_AUTHORITY.md`](CONFIG_AUTHORITY.md) for the full list.

### Precedence (Highest Wins Last)

```
1. Schema defaults   (lib/tuneables_schema.py)     <- hardcoded baseline
2. Versioned baseline (config/tuneables.json)       <- checked into git
3. Runtime overrides  (~/.spark/tuneables.json)     <- your local edits
4. Env overrides      (SPARK_* env vars)            <- highest priority
```

You almost always edit layer 3 (`~/.spark/tuneables.json`). Layer 2 (`config/tuneables.json`) is the project baseline and shouldn't be edited for local use. Env overrides (layer 4) are for temporary or deployment-specific needs.

### Hot-Reload

Most modules pick up changes automatically — no restart needed:

| Modules with hot-reload | Section |
|-------------------------|---------|
| `advisory_engine.py` | `advisory_engine` |
| `advisory_gate.py`, `advisory_state.py` | `advisory_gate` |
| `advisor.py` | `advisor` |
| `meta_ralph.py` | `meta_ralph` |
| `pipeline.py` | `pipeline` |
| `bridge_cycle.py` | `bridge_worker` |
| `queue.py` | `queue` |
| `eidos/models.py` | `eidos` |
| `advisory_synthesizer.py` | `synthesizer` |
| `advisory_packet_store.py` | `advisory_packet_store` |
| `advisory_prefetch_worker.py` | `advisory_prefetch` |
| `memory_capture.py` | `memory_capture` |
| `request_tracker.py` | `request_tracker` |
| `validate_and_store.py` | `flow` |

**Restart required** for: `semantic_retriever.py` (`semantic`, `triggers`), `context_sync.py` (`sync`).

### Reconciliation

On startup, Spark runs `reconcile_with_defaults()` which removes stale copies from `~/.spark/tuneables.json` — if a runtime value matches the baseline exactly, it's stripped so the code default wins. This prevents old overrides from defeating newer defaults after upgrades.

The `auto_tuner` section is exempt (its values are intentionally evolved).

### Auto-Tuner

The auto-tuner runs every 12 hours and adjusts `auto_tuner.source_boosts` based on measured effectiveness. It writes to `~/.spark/tuneables.json` but only touches its own section unless `apply_cross_section_recommendations` is explicitly enabled.

Disable it:
```json
{ "auto_tuner": { "enabled": false } }
```

Monitor it:
```bash
python -c "from lib.config_authority import resolve_section; import json; s=resolve_section('auto_tuner'); print(json.dumps({k:v for k,v in s.data.items() if k in ('enabled','mode','source_boosts','last_run')}, indent=2))"
```

### Common Tuneables

| What | Key | Default | Effect |
|------|-----|---------|--------|
| Quality gate strictness | `meta_ralph.quality_threshold` | `4.5` | Higher = fewer learnings pass (0-10) |
| Advice items per tool call | `advisory_gate.max_emit_per_call` | `2` | How many tips shown per action |
| Advisory time budget | `advisory_engine.max_ms` | `4000` | ms budget for advisory engine |
| Repeat cooldown | `advisory_gate.advice_repeat_cooldown_s` | `300` | Seconds before same advice re-emits |
| Shown advice TTL | `advisory_gate.shown_advice_ttl_s` | `600` | How long "already shown" suppression lasts |
| Tool cooldown | `advisory_gate.tool_cooldown_s` | `15` | Same-tool suppression cooldown (s) |
| Retrieval min score | `advisor.min_rank_score` | `0.4` | Floor for advisory ranking fusion score |
| Mind sync enabled | `bridge_worker.mind_sync_enabled` | `true` | Whether bridge syncs to Mind |
| Prefetch queue | `advisory_engine.prefetch_queue_enabled` | `false` | Predictive advisory pre-computation |
| Semantic retrieval | `semantic.enabled` | `true` | Enable semantic matching |

### Troubleshooting Tuneables

**"I changed a value but nothing happened"**
- Check if the module has hot-reload (table above). If not, restart services.
- Env vars set after startup are ignored — restart required.
- Verify JSON is valid: `python -c "import json; json.load(open('path/to/tuneables.json'))"`

**"My override disappeared after restart"**
- Reconciliation strips values matching the baseline. If you intentionally want a value that happens to match the baseline, that's fine — the baseline already provides it.

**"Lock file stuck"**
- Delete `~/.spark/tuneables.json.lock` if a process crashed mid-write.

**"How do I see what's active?"**
```bash
python -c "
from lib.config_authority import resolve_section
section = resolve_section('advisory_gate')
for k, v in sorted(section.data.items()):
    print(f'  {k} = {v!r}  [{section.sources.get(k, \"?\")}]')
"
```

## Claude Code Integration

Use the maintained integration flow in `docs/claude_code.md`.

Minimal path:

```bash
# macOS/Linux
./scripts/install_claude_hooks.sh

# Windows (PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\install_claude_hooks.ps1
```

Then merge `~/.claude/spark-hooks.json` into `~/.claude/settings.json`.

Note: generated hooks use `python`/`python3` from PATH. If you run Spark in a venv,
replace the hook command with that venv interpreter path.

## Codex Integration (Optional)

Use when you want Codex sessions to receive `SPARK_CONTEXT_FOR_CODEX.md` and
`SPARK_ADVISORY_PAYLOAD.json`.

```bash
# Preferred: launch Codex through the wrapper
scripts/spark-codex.sh
# Windows
scripts\\spark-codex.bat
```

What the wrapper does:

- sets `SPARK_SYNC_TARGETS=codex` if not already set
- sets `CMD` from `SPARK_CODEX_CMD` or `CODEX_CMD` (fallback to `codex`)
- runs `python -m spark.cli sync-context` before launching Codex

If you run sync manually:

```bash
# Either of these enables Codex output during sync
set SPARK_SYNC_TARGETS=codex
set SPARK_CODEX_CMD=codex
# or
python -m spark.cli sync-context
```

Verify Codex sync artifacts are present in the current project:

```bash
test -f SPARK_CONTEXT_FOR_CODEX.md && test -f SPARK_ADVISORY_PAYLOAD.json && echo "ok"
python -m lib.integration_status
```

If status still reports missing Codex sync, confirm:

- the command runs in the same shell/environment where `SPARK_CODEX_CMD` or `CODEX_CMD` is set
- `python -m spark.cli sync-context` is completing successfully
- `SPARK_SYNC_TARGETS` is not overridden to exclude `codex`

## Directory Structure

After running, Spark creates:

```
~/.spark/                      # Config and data
â”œâ”€â”€ cognitive_insights.json    # Raw learnings
â”œâ”€â”€ mind_sync_state.json       # Sync tracking
â”œâ”€â”€ exposures.jsonl            # Surfaced insights (prediction inputs)
â”œâ”€â”€ predictions.jsonl          # Prediction registry
â”œâ”€â”€ outcomes.jsonl             # Outcomes log (skills/orchestration/project)
â”œâ”€â”€ skills_index.json          # Cached skills index
â”œâ”€â”€ skills_effectiveness.json  # Skill success/fail counters
â”œâ”€â”€ orchestration/
â”‚   â”œâ”€â”€ agents.json            # Registered agents
â”‚   â””â”€â”€ handoffs.jsonl         # Handoff history
â””â”€â”€ queue/
    â””â”€â”€ events.jsonl           # Event queue

.learnings/                    # In your project
â”œâ”€â”€ LEARNINGS.md              # Human-readable insights
â””â”€â”€ ERRORS.md                 # Error patterns

AGENTS.md                      # Promoted workflow patterns
CLAUDE.md                      # Promoted conventions
```

## CLI Commands Reference

| Command | Description |
|---------|-------------|
| `status` | Show full system status |
| `services` | Show daemon/service status |
| `up` | Start background services (`--lite` for core-only) |
| `ensure` | Start missing services if not running |
| `down` | Stop background services |
| `health` | Quick health check |
| `learnings` | List recent cognitive insights |
| `write` | Write insights to markdown |
| `promote` | Auto-promote high-value insights |
| `sync-context` | Sync bootstrap context to platform files |
| `decay` | Preview/apply decay-based pruning |
| `sync` | Sync to Mind (if running) |
| `queue` | Process offline sync queue |
| `process` | Run bridge worker cycle or drain backlog |
| `validate` | Run validation scan on recent events |
| `events` | Show recent captured events |

## Troubleshooting

### "Mind API: Not available"

Mind is not reachable. Try:
- Start services with Mind enabled: `python -m spark.cli up` (default includes built-in `mind_server.py`)
- Verify Mind health: `curl http://127.0.0.1:${SPARK_MIND_PORT:-8080}/health`
- Or ignore it - Spark still works offline and queues sync for later

### "requests not installed"

```bash
pip install requests
```

### Maintenance script locations

- One-time cleanup scripts now live under `scripts/maintenance/one_time/`.
- Archived manual LLM bridge diagnostics live under `scripts/experimental/manual_llm/`.
- Old top-level cleanup paths remain as compatibility shims.

### Learnings not appearing

Check that the hook is configured correctly and the path is absolute.

If the queue is large or processing stalled, run:

```bash
python -m spark.cli process --drain
```

### Extra logging (optional)

Enable debug logs temporarily when troubleshooting:

```bash
set SPARK_DEBUG=1
```

Tip: leave it off for normal usage to avoid log noise.

### Validation Loop (v1)

The current validation loop focuses on user preferences + communication insights.
Recommended: let it run for a day or two to confirm low false positives, then
expand scope if needed.

## Next Steps

1. **Integrate with your workflow** - Set up the hooks
2. **Confirm services** - `python -m spark.cli services` and `python -m spark.cli health`
3. **Review learnings** - `python -m spark.cli learnings`
4. **Promote insights** - `python -m spark.cli promote`

---

*Part of the Vibeship Ecosystem*

