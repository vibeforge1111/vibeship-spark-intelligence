# Spark Chips - Domain-Specific Intelligence

**Chips teach Spark *what* to learn, not just *how* to learn.**
Navigation hub: `docs/GLOSSARY.md`

## Open-Source Launch Behavior

Spark OSS ships the chip architecture, but chip processing is disabled by default.
To keep the default launch minimal and safe, enable chips via tuneables:

```json
// ~/.spark/tuneables.json  (canonical method)
{
  "feature_flags": {
    "premium_tools": true,
    "chips_enabled": true
  }
}
```

Or via env vars (overrides for CI/containers):

```bash
set SPARK_PREMIUM_TOOLS=1
set SPARK_CHIPS_ENABLED=1
```

In OSS default, both flags are `false`, so chip loading and advice contributions are disabled.

See `docs/CONFIG_AUTHORITY.md` for the full precedence model (schema defaults → versioned baseline → runtime overrides → env overrides).

```
+------------------+     +------------------+     +------------------+
|   spark-core     |     |   marketing      |     |   your-domain    |
|   (coding)       |     |   (campaigns)    |     |   (custom)       |
+------------------+     +------------------+     +------------------+
         |                        |                        |
         v                        v                        v
+------------------------------------------------------------------+
|                        SPARK RUNTIME                              |
|  Triggers -> Observers -> Learners -> Outcomes -> Insights        |
+------------------------------------------------------------------+
         |
         v
+------------------+
|  COGNITIVE       |
|  INSIGHTS        |
|  (validated)     |
+------------------+
```

## What Are Chips?

Chips are **YAML specifications** that tell Spark:
- What patterns to watch for (triggers)
- What data to capture (observers)
- What to learn from it (learners)
- How to measure success (outcomes)
- What questions to ask (questions)

Think of chips as **domain experts in a box** - each one knows what matters in its field.

Schema-first operating model:
- `docs/CHIPS_SCHEMA_FIRST_PLAYBOOK.md`

### Supported Chip Formats

Spark supports three chip formats:
- `single`: one `*.chip.yaml` file
- `multifile`: `chip.yaml` plus modular `triggers.yaml`, `observers.yaml`, `outcomes.yaml`, etc.
- `hybrid`: one `*.chip.yaml` with `includes:` to merge modular files

Format preference is controlled via `chips_runtime.preferred_format` in tuneables (default: `multifile`), or the env override `SPARK_CHIP_PREFERRED_FORMAT`.

## Quick Start

```bash
# Enable chips (premium)
set SPARK_CHIPS_ENABLED=1

# List installed chips
spark chips list

# Install a chip
spark chips install chips/spark-core.chip.yaml

# Activate it
spark chips activate spark-core

# See what questions it asks
spark chips questions spark-core

# Check its insights
spark chips insights spark-core
```

## Anatomy of a Chip

```yaml
# Identity - Who is this chip?
chip:
  id: marketing-campaigns
  name: Marketing Campaign Intelligence
  version: 1.0.0
  description: |
    Learns what makes marketing campaigns succeed.
    Tracks metrics, messaging, and audience signals.
  author: Vibeship
  license: MIT
  human_benefit: "Improve marketing outcomes without manipulation."
  harm_avoidance:
    - "No deceptive or coercive messaging"
    - "No exploitation of vulnerable audiences"
  risk_level: medium
  safety_tests:
    - "no_deceptive_growth"
    - "no_harmful_targeting"
  activation: opt_in
  domains:
    - marketing
    - growth
    - campaigns

# Triggers - When does this chip activate?
triggers:
  patterns:
    - "campaign performed"
    - "CTR was"
    - "conversion rate"
    - "audience responded"
  events:
    - user_prompt
    - post_tool

# Observers - What data to capture?
observers:
  - name: campaign_result
    description: Captures campaign performance
    triggers:
      - "campaign"
      - "performed"
      - "results"
    capture:
      required:
        metric: The key metric
        value: The result
      optional:
        channel: Marketing channel
        audience: Target audience

# Learners - What patterns to detect?
learners:
  - name: channel_effectiveness
    description: Learns which channels work best
    type: correlation
    input:
      fields:
        - channel
        - audience
    output:
      fields:
        - conversion_rate
        - engagement
    learn:
      - "Which channels convert best"
      - "Which audiences engage most"

# Outcomes - How to measure success?
outcomes:
  positive:
    - condition: "conversion_rate > 0.02"
      weight: 1.0
      insight: "High-converting campaign"
  negative:
    - condition: "bounce_rate > 0.7"
      weight: 0.8
      insight: "High bounce - messaging mismatch"

# Questions - What to ask the user?
questions:
  - id: mkt_kpi
    question: What is the primary KPI for this campaign?
    category: metric
    affects_learning:
      - channel_effectiveness

  - id: mkt_audience
    question: Who is the target audience?
    category: goal
    affects_learning:
      - campaign_result
```

## Core Concepts

### Activation

Chips can be auto-activated from content matching, or left opt-in:

- `activation: auto` - eligible for auto-activation based on content.
- `activation: opt_in` - only activates when explicitly enabled.

### 1. Triggers

Triggers determine when a chip activates:

| Type | Example | Use Case |
|------|---------|----------|
| `patterns` | `"worked because"` | Natural language signals |
| `events` | `post_tool` | Hook events from Claude Code |
| `tools` | `{name: "Bash"}` | Specific tool usage |

Note: Claude Code hook names (PostToolUse, PostToolUseFailure, UserPromptSubmit)
are normalized to runtime event types (`post_tool`, `post_tool_failure`,
`user_prompt`). Use runtime names in chip triggers; add legacy hook names only
if your environment emits them directly.

Runtime quality gate:
- Chip insights are scored before storage.
- Low-value entries are filtered via `SPARK_CHIP_MIN_SCORE` (default `0.35`).
- Balanced mode also enforces confidence (`SPARK_CHIP_MIN_CONFIDENCE`, default `0.7`),
  safety policy checks, and evidence/outcome presence (`SPARK_CHIP_GATE_MODE=balanced`).

### 2. Observers

Observers capture structured data when triggered:

```yaml
observers:
  - name: success_pattern
    triggers:
      - "worked because"
      - "fixed by"
    insight_template: "{pattern} worked because {reason}"
    capture:
      required:
        pattern: What worked
      optional:
        reason: Why it worked
```

### 3. Learners

Learners detect patterns across observations:

| Type | Purpose |
|------|---------|
| `correlation` | Find relationships between inputs and outputs |
| `pattern` | Detect recurring patterns |
| `optimization` | Learn optimal approaches |

### 4. Outcomes

Outcomes validate insights with real results:

```yaml
outcomes:
  positive:
    - condition: "success == true"
      insight: "Approach validated"
  negative:
    - condition: "error_count > 3"
      insight: "Approach needs revision"
```

### 5. Questions

Questions scope what gets learned:

```yaml
questions:
  - id: core_stack
    question: What is the primary tech stack?
    category: goal
    phase: discovery
    affects_learning:
      - tool_effectiveness
```

## Built-in Chips (premium runtime enabled via SPARK_CHIPS_ENABLED)

### spark-core (Coding Intelligence)

**Domains:** coding, development, debugging, tools

**Triggers:**
- "worked because", "failed because"
- "fixed by", "the issue was"
- "prefer", "always", "never"

**Questions:**
- What is the primary tech stack?
- What quality signals matter most?
- What should we avoid?

**Learns:**
- Which tools work best
- Common error patterns and fixes
- User coding preferences

In the OSS default launch mode, these chips are present in code but not usable until
you enable chips with `SPARK_CHIPS_ENABLED=1`.

## Creating Your Own Chip

### Step 1: Define Identity

```yaml
chip:
  id: my-domain
  name: My Domain Intelligence
  version: 1.0.0
  domains:
    - my-area
```

### Step 2: Set Triggers

What signals indicate this domain?

```yaml
triggers:
  patterns:
    - "domain-specific phrase"
    - "another signal"
```

### Step 3: Define Observers

What data to capture?

```yaml
observers:
  - name: my_observation
    triggers:
      - "capture this"
    capture:
      required:
        key_field: Description
```

### Step 4: Add Learners

What patterns to detect?

```yaml
learners:
  - name: my_learner
    type: correlation
    learn:
      - "What correlates with success"
```

### Step 5: Define Outcomes

How to measure success?

```yaml
outcomes:
  positive:
    - condition: "metric > threshold"
      insight: "This approach works"
```

### Step 6: Add Questions

What context helps learning?

```yaml
questions:
  - id: domain_goal
    question: What is the goal?
    category: goal
    affects_learning:
      - my_learner
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `spark chips list` | List all installed chips |
| `spark chips install <path>` | Install a chip |
| `spark chips uninstall <id>` | Remove a chip |
| `spark chips activate <id>` | Enable chip processing |
| `spark chips deactivate <id>` | Disable chip |
| `spark chips status <id>` | Show chip details |
| `spark chips insights <id>` | Show chip insights |
| `spark chips questions <id>` | Show chip questions |
| `spark chips test <id>` | Test chip with sample |

## How Chips Learn

```
User Action
    |
    v
+-------------------+
| Event Queue       |  <- Hook captures event
+-------------------+
    |
    v
+---------------------------+
| Chip Loader               |  <- single/multifile/hybrid
+---------------------------+
    |
    v
+---------------------------+
| Chip Router               |  <- Normalized event/tool/pattern matching
+---------------------------+
    |
    v
+---------------------------+
| Chip Runtime              |  <- Observer execution + extraction
+---------------------------+
    |
    v
+---------------------------+
| Chip Scoring Gate         |  <- Filters low-value noise before storage
+---------------------------+
    |
    v
+---------------------------+
| Chip Evolution + Merger   |  <- Trigger quality + cognitive merge
+---------------------------+
```

## Best Practices

1. **Start Specific** - Focus on one domain well before expanding
2. **Use Real Signals** - Triggers should match actual user language
3. **Capture What Matters** - Only required fields that affect learning
4. **Define Clear Outcomes** - Measurable success/failure conditions
5. **Ask Scoped Questions** - Questions that directly affect learners

## Example Chips

See the `chips/` directory for examples:
- `spark-core.chip.yaml` - Coding and development
- More coming soon...

## Architecture

```
chips/
  spark-core.chip.yaml     # Built-in coding chip
  multifile/<chip>/chip.yaml
  hybrid/<chip>.chip.yaml
  my-custom.chip.yaml      # Your custom chips

lib/chips/
  loader.py                # Single/multifile/hybrid parsing
  schema.py                # Chip validation
  registry.py              # Install/activate tracking
  router.py                # Event-to-chip matching
  runtime.py               # Observer execution + quality gate
  scoring.py               # Insight scoring
  store.py                 # Per-chip insight storage

~/.spark/chips/
  chip_registry.json       # Installed chips registry
  chips/                   # User-installed chip files/bundles
  chip_insights/           # Per-chip data storage
    spark-core.jsonl
```

---

*Chips are the foundation of domain-specific intelligence in Spark. They teach the system what matters in your field, making every interaction smarter.*
