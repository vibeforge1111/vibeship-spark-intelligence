# Obsidian Observatory Guide

The Observatory transforms Spark Intelligence's internal state files into a human-readable Obsidian vault, showing the full 12-stage intelligence pipeline — from event capture through quality gates through cognitive learning through EIDOS through advisory to promotion.

## Quick Start

### Prerequisites

- [Obsidian](https://obsidian.md) installed
- Python 3.10+
- Spark Intelligence repository cloned

### Generate the Observatory

```bash
python scripts/generate_observatory.py --force --verbose
```

This creates ~460+ markdown files in your vault directory (default: `~/Documents/Obsidian Vault/Spark-Intelligence-Observatory`).

### Open in Obsidian

1. Open Obsidian
2. **Open folder as vault** — select `Spark-Intelligence-Observatory`
3. Navigate to `_observatory/flow.md` — this is your entry point

### Auto-Sync

When Spark's pipeline is running, the observatory auto-refreshes every 120 seconds (configurable). No manual regeneration needed during normal operation.

## Vault Structure

```
Spark-Intelligence-Observatory/
  _observatory/                     # Auto-generated — DO NOT EDIT
    flow.md                         # Main dashboard + Mermaid pipeline diagram
    flow.canvas                     # Spatial Canvas view of the pipeline
    stages/
      01-event-capture.md           # Hook integration, session tracking
      02-queue.md                   # Event buffering, overflow
      03-pipeline.md                # Batch processing, learning yield
      04-memory-capture.md          # Importance scoring, domain detection
      05-meta-ralph.md              # Quality gate, roast verdicts
      06-cognitive-learner.md       # Insight store, reliability tracking
      07-eidos.md                   # Episodes, distillations, predict-evaluate
      08-advisory.md                # Retrieval, ranking, effectiveness
      09-promotion.md               # Target files, promotion log
      10-chips.md                   # Domain modules, per-chip activity
      11-predictions.md             # Outcomes, surprise tracking
      12-tuneables.md               # Configuration, hot-reload
    explore/
      _index.md                     # Master explorer index
      cognitive/                    # Individual cognitive insights (with detail pages)
      distillations/                # Individual EIDOS distillations (with detail pages)
      episodes/                     # Individual EIDOS episodes (with detail pages + steps)
      verdicts/                     # Individual Meta-Ralph verdicts (with detail pages)
      promotions/                   # Promotion log entries (index only)
      advisory/                     # Advisory effectiveness breakdown (index only)
      routing/                      # Retrieval router decisions (index only)
      tuning/                       # Tuneable evolution history + impact analysis (index only)
      decisions/                    # Advisory decision ledger - emit/suppress/block (index only)
      feedback/                     # Implicit feedback loop - followed/ignored (index only)
  Dashboard.md                      # Personal Dataview dashboard (NOT auto-generated, safe to edit)
  packets/                          # Advisory packets (existing, separate system)
    index.md
    <packet_id>.md
  watchtower.md                     # Advisory watchtower (existing, separate system)
```

## The Flow Dashboard

Open `_observatory/flow.md` to see the main dashboard.

### System Health Table

The top table shows key metrics with status badges (including Meta-Ralph pass rate, advisory emit rate, and implicit feedback follow rate):

| Badge | Meaning |
|-------|---------|
| `healthy` | Normal operation |
| `warning` | Degraded but functional (e.g., pipeline idle >5 min) |
| `critical` | Needs attention (e.g., pipeline idle >10 min) |

### Mermaid Pipeline Diagram

Below the health table is a live Mermaid flowchart showing all 12 stages with embedded metrics. Each node shows:

- Stage name
- Current count/rate (e.g., "~2,400 pending", "8.3 ev/s")
- Recent timestamp or status

The diagram shows the actual data flow: events enter via hooks, pass through the queue, get processed by the pipeline, scored by Memory Capture, gated by Meta-Ralph, stored by Cognitive Learner, and retrieved by Advisory. EIDOS runs parallel for episodic intelligence. Chips provide domain-specific learning. Predictions close the feedback loop.

**Tip**: If Mermaid diagrams aren't rendering, go to Obsidian Settings > Core plugins > enable "Mermaid diagrams".

### Stage Links

Numbered links take you to each stage's detail page. Each link includes a short description of what that stage does.

### Quick Links

At the bottom, find links to:
- **Explore Individual Items** — browse raw data from every store
- **Advisory Watchtower** — the existing advisory deep-dive
- **Advisory Packet Catalog** — the existing packet browser

## Stage Detail Pages

Each of the 12 stage pages (`_observatory/stages/NN-name.md`) follows the same template:

1. **Header** — upstream/downstream stage links for navigation
2. **Purpose** — 1-2 sentence description of what this stage does
3. **Health Table** — stage-specific metrics with status indicators
4. **Recent Activity** — last N items from the relevant log (verdicts, advice, etc.)
5. **Source Files** — links to the Python module and `~/.spark/` state files

### What to look for per stage

| Stage | Key Metrics | Signals of Interest |
|-------|------------|---------------------|
| 01-Event Capture | Last cycle time, heartbeat age | Stale heartbeat = pipeline stopped |
| 02-Queue | Pending count, file size | Growing queue = pipeline can't keep up |
| 03-Pipeline | Processing rate, empty cycles | Consecutive empty = no new data |
| 04-Memory Capture | Pending count, category distribution | Category imbalance = narrow learning |
| 05-Meta-Ralph | Verdict distribution, pass rate | Too many passes = quality too loose |
| 06-Cognitive | Insight count, top reliability items | Low reliability = unstable insights |
| 07-EIDOS | Episode/distillation counts | 0 distillations = distillation pipeline broken |
| 08-Advisory | Follow rate, source effectiveness | Low follow rate = advice not useful |
| 09-Promotion | Target distribution, recent activity | No recent promotions = threshold too high |
| 10-Chips | Active count, per-chip size | Large chips need rotation |
| 11-Predictions | Outcome count, link rate | Low links = prediction-outcome matching broken |
| 12-Tuneables | Section listing | Shows current config in human-readable form |

## The Explorer

Open `_observatory/explore/_index.md` to see all browsable data stores.

### Explorer Sections

| Section | Data Source | Detail Pages? | What You See |
|---------|-----------|---------------|-------------|
| **Cognitive Insights** | `~/.spark/cognitive_insights.json` | Yes (per insight) | Key, category, reliability, validations, evidence |
| **EIDOS Distillations** | `~/.spark/eidos.db` | Yes (per distillation) | Statement, type, confidence, domains, triggers |
| **EIDOS Episodes** | `~/.spark/eidos.db` | Yes (per episode + steps) | Goal, outcome, phase, prediction vs evaluation |
| **Meta-Ralph Verdicts** | `~/.spark/meta_ralph/roast_history.json` | Yes (per verdict) | Score breakdown, input text, issues found |
| **Promotion Log** | `~/.spark/promotion_log.jsonl` | No (index table) | Target distribution, recent activity |
| **Advisory** | `~/.spark/advisor/effectiveness.json` | No (index table) | Source effectiveness, follow rate, recent advice |
| **Retrieval Routing** | `~/.spark/advisor/retrieval_router.jsonl` | No (index table) | Route distribution, reasons, complexity scores |
| **Tuneable Evolution** | `~/.spark/auto_tune_log.jsonl` | No (index table) | Parameter changes, impact analysis (before/after follow rate) |
| **Advisory Decisions** | `~/.spark/advisory_decision_ledger.jsonl` | No (index table) | Emit/suppress/block decisions, suppression reasons, source counts |
| **Implicit Feedback** | `~/.spark/advisor/implicit_feedback.jsonl` | No (index table) | Followed/ignored signals, per-tool follow rates, source effectiveness |

### Navigating Detail Pages

Each detail page includes:
- YAML frontmatter (used by Dataview plugin for queries)
- Backlinks to the section index and main flow dashboard
- Full data from the source store

**Example**: A cognitive insight page shows the insight text, reliability score, validation count, evidence list, and counter-examples.

## Canvas View

Open `_observatory/flow.canvas` to see the spatial layout.

The Canvas shows each pipeline stage as a card positioned in a left-to-right flow. Cards are linked by directional arrows showing data movement. You can:

- Pan and zoom to focus on specific areas
- Click any card to open the corresponding stage page
- Rearrange cards if you prefer a different layout (your layout persists)

**Note**: Canvas is an Obsidian core feature. No plugins needed.

## Commands Reference

### Manual Generation

```bash
# Full generation (all pages + canvas + explorer)
python scripts/generate_observatory.py --force --verbose

# Skip canvas generation (faster)
python scripts/generate_observatory.py --force --no-canvas --verbose

# Normal mode (respects cooldown — won't regenerate within 120s of last sync)
python scripts/generate_observatory.py
```

### Auto-Sync

The observatory automatically regenerates when Spark's bridge cycle runs, subject to a cooldown. This is configured in `lib/bridge_cycle.py` and requires no manual setup.

The hook is:
```python
# bridge_cycle.py line 715
try:
    from lib.observatory import maybe_sync_observatory
    maybe_sync_observatory(stats)
except Exception:
    pass
```

## Configuration & Fine-Tuning

All observatory settings live in the `observatory` section of tuneables.

### Where to configure

| File | Purpose |
|------|---------|
| `~/.spark/tuneables.json` | Runtime config (takes priority) |
| `config/tuneables.json` | Version-controlled defaults |

Edit either file's `observatory` section. Runtime config takes priority.

### All tuneable fields

| Field | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `enabled` | bool | `true` | — | Master switch for observatory generation |
| `auto_sync` | bool | `true` | — | Auto-sync on every bridge cycle |
| `sync_cooldown_s` | int | `120` | 10–3600 | Minimum seconds between auto-syncs |
| `vault_dir` | str | `~/Documents/...` | — | Path to Obsidian vault directory |
| `generate_canvas` | bool | `true` | — | Generate `.canvas` spatial view |
| `max_recent_items` | int | `20` | 5–100 | Max recent items shown per stage page |
| `explore_cognitive_max` | int | `200` | 1–5000 | Max cognitive insights exported as pages |
| `explore_distillations_max` | int | `200` | 1–5000 | Max EIDOS distillations exported |
| `explore_episodes_max` | int | `100` | 1–2000 | Max EIDOS episodes exported |
| `explore_verdicts_max` | int | `100` | 1–5000 | Max Meta-Ralph verdicts exported |
| `explore_promotions_max` | int | `200` | 1–5000 | Max promotion log entries exported |
| `explore_advice_max` | int | `200` | 1–5000 | Max advisory log entries exported |
| `explore_routing_max` | int | `100` | 1–5000 | Max retrieval routing decisions exported |
| `explore_tuning_max` | int | `200` | 1–5000 | Max tuneable evolution entries exported |
| `explore_decisions_max` | int | `200` | 1–5000 | Max advisory decision ledger entries exported |
| `explore_feedback_max` | int | `200` | 1–5000 | Max implicit feedback entries exported |

### Example: Increase explorer limits

```json
{
  "observatory": {
    "explore_cognitive_max": 500,
    "explore_distillations_max": 500,
    "explore_episodes_max": 200
  }
}
```

Then regenerate: `python scripts/generate_observatory.py --force --verbose`

### Example: Change vault directory

```json
{
  "observatory": {
    "vault_dir": "D:\\MyVaults\\SparkObservatory"
  }
}
```

### Example: Disable auto-sync (manual only)

```json
{
  "observatory": {
    "auto_sync": false
  }
}
```

### Performance considerations

- Keep individual explore limits below **500** for smooth Obsidian performance
- Total generated files should stay under **5,000** (Obsidian can handle more but gets slower)
- The full observatory generates in under 1 second on typical hardware
- Canvas generation adds ~50ms

## Recommended Obsidian Plugins

### Dataview (strongly recommended)

Install **Dataview** from Obsidian Community Plugins. It lets you query the YAML frontmatter on every observatory page.

See the [Dataview Query Examples](#dataview-query-examples) section below.

### Graph Analysis

The **Graph Analysis** plugin helps visualize clusters of related insights, episodes, and verdicts in Obsidian's graph view.

### Obsidian Git

Use **Obsidian Git** to version-control your vault. This lets you track how your intelligence data evolves over time.

## Dataview Dashboard

The vault includes a `Dashboard.md` file at the vault root. This is a **personal note** — it's not auto-generated and won't be overwritten by the observatory. It contains pre-built Dataview queries for:

- High-reliability insights (90%+)
- Promoted insights
- Recent successful and failed episodes
- Meta-Ralph verdict summary
- Top distillations by confidence and retrieval count
- Advisory effectiveness, implicit feedback, and decision outcomes
- System evolution (tuneable changes, routing health)
- Custom query templates you can fill in

Pin it as a tab alongside `flow.md` for a complete monitoring setup.

## Dataview Query Examples

All observatory pages include YAML frontmatter. Install the Dataview plugin and paste these queries into any Obsidian note.

### High-reliability cognitive insights

````markdown
```dataview
TABLE reliability, validations, category
FROM "/_observatory/explore/cognitive"
WHERE type = "spark-cognitive-insight" AND reliability >= 0.9
SORT reliability DESC
LIMIT 20
```
````

### Successful EIDOS episodes

````markdown
```dataview
TABLE goal, step_count, started
FROM "/_observatory/explore/episodes"
WHERE type = "spark-eidos-episode" AND outcome = "success"
SORT started DESC
LIMIT 15
```
````

### Meta-Ralph verdicts with high scores

````markdown
```dataview
TABLE verdict, total_score, source
FROM "/_observatory/explore/verdicts"
WHERE type = "spark-metaralph-verdict" AND total_score >= 7
SORT total_score DESC
```
````

### Promoted cognitive insights

````markdown
```dataview
TABLE key, reliability, promoted_to
FROM "/_observatory/explore/cognitive"
WHERE type = "spark-cognitive-insight" AND promoted = true
SORT reliability DESC
```
````

### EIDOS distillations by type

````markdown
```dataview
TABLE distillation_type, confidence, validation_count, times_retrieved
FROM "/_observatory/explore/distillations"
WHERE type = "spark-eidos-distillation"
SORT confidence DESC
LIMIT 20
```
````

### Failed episodes (investigation)

````markdown
```dataview
TABLE goal, phase, step_count, started
FROM "/_observatory/explore/episodes"
WHERE type = "spark-eidos-episode" AND outcome = "failure"
SORT started DESC
```
````

## Tips & Best Practices

1. **Don't edit `_observatory/` files** — they're regenerated on every sync. Your edits will be overwritten.

2. **Create personal notes alongside** — Use a different prefix (e.g., `notes/` or `journal/`) for your own annotations. These won't be touched by the observatory.

3. **Use bookmarks for tracking** — Bookmark interesting insights or episodes in Obsidian. Bookmarks persist across regenerations since they reference file paths that stay stable.

4. **Pin `flow.md` as a tab** — Keep the flow dashboard always visible for a quick health check.

5. **Use Graph View** — Obsidian's graph view shows how pages interconnect. Filter by `_observatory` to see only observatory pages.

6. **Start from the flow, drill down** — Use `flow.md` > stage page > explorer as your navigation hierarchy.

7. **Check stage upstream/downstream links** — Every stage page links to its input and output stages. Follow the chain to trace data flow.

8. **Use the Canvas for presentations** — The `flow.canvas` is great for explaining the system to others.

## Troubleshooting

### "No data showing" or empty pages

The observatory reads from `~/.spark/` state files. If these don't exist yet:
1. Run Spark's pipeline at least once to generate state files
2. Then regenerate: `python scripts/generate_observatory.py --force --verbose`

### Mermaid diagrams not rendering

1. Go to Obsidian **Settings > Core plugins**
2. Ensure "Mermaid diagrams" is enabled (it's a core plugin, on by default)

### Canvas is blank

1. Check that `generate_canvas` is `true` in your tuneables
2. Regenerate with: `python scripts/generate_observatory.py --force --verbose`
3. Open `flow.canvas` from the file explorer (not via wiki-link)

### Stale data

The observatory shows data as of the last sync. If data looks old:
1. Check if the bridge cycle is running (look at pipeline stage's "last cycle" timestamp)
2. Run manual generation: `python scripts/generate_observatory.py --force`
3. Check `sync_cooldown_s` — lower it for more frequent updates

### Obsidian is slow

If the vault feels sluggish:
1. Reduce explorer limits (especially `explore_cognitive_max` and `explore_verdicts_max`)
2. Disable canvas generation if you don't use it: `"generate_canvas": false`
3. Keep total explorer limits under 500 per section

### "Permission denied" or "File in use"

On Windows, if another process has a lock on `eidos.db` or JSONL files:
1. The observatory uses 2-second timeouts for SQLite — it may skip EIDOS data temporarily
2. JSONL readers are read-only and shouldn't conflict
3. If persistent, check for stale `.cognitive.lock` files in `~/.spark/`

## Coexistence with Advisory Packets

The observatory and the existing advisory export system are **independent**:

| System | Directory | Generator | Auto-sync |
|--------|-----------|-----------|-----------|
| Observatory | `_observatory/` | `lib/observatory/` | bridge_cycle hook (120s cooldown) |
| Advisory Packets | `packets/` + `watchtower.md` | `lib/advisory_packet_store.py` | advisory_packet_store sync |

They share the same Obsidian vault but never write to each other's directories. The observatory links TO the advisory pages (watchtower and packets/index) for easy navigation.

For advisory-specific guidance, see `docs/ADVISORY_OBSIDIAN_PLAYBOOK.md`.

## Coexistence with Learning Systems Bridge

Spark now has an external-learning ingress bridge (`lib/learning_systems_bridge.py`) that writes:

- `~/.spark/learning_systems/insight_ingest_audit.jsonl`
- `~/.spark/learning_systems/tuneable_proposals.jsonl`

These files are append-only diagnostics/queue artifacts. They are safe to expose as read-only explorer pages in Observatory, and they should never be edited manually from the vault.
