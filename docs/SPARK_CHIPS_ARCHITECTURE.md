# Spark Chips: Pluggable Intelligence for Every Domain

> _"Chips are to Spark what apps are to a smartphone — they teach it how to think about your world."_

---

## Implementation Status (2026-02-17)

This document mixes architecture vision with implementation details.

- `implemented` in this repo:
  - `lib/chips/{loader,router,runtime,schema,policy,registry,runner,store,scoring,evolution}.py`
  - `lib/chip_merger.py`
- `planned/vision`:
  - open ecosystem and registry distribution surfaces described here
  - some reference examples and companion docs may live in archived docs or external repos

## Executive Summary

Spark Chips transform Spark from a monolithic learning system into an **open platform for domain-specific intelligence**. Instead of Spark knowing only how to learn from code and tools, chips teach Spark how to learn from _anything_ — marketing campaigns, sales deals, factory operations, team dynamics, financial decisions, and beyond.

**The Problem Today:**

- Spark learns one way about everything (tool patterns, user preferences)
- No domain expertise — doesn't understand what "success" means in marketing vs. engineering vs. sales
- Can't evolve its learning strategies based on domain-specific outcomes
- Intelligence is locked, not extensible

**The Chips Solution:**

- Pluggable modules that teach Spark _how to think_ about a domain
- Each chip defines: what to observe, what patterns matter, what success looks like
- Chips evolve themselves based on outcomes
- Open ecosystem — anyone can create and share chips

---

## What is a Chip?

A **Chip** is a YAML specification that teaches Spark how to be intelligent about a specific domain.

Think of it like this:

- A smartphone is powerful, but apps make it _useful_
- Spark is the learning engine, but chips make it _intelligent about your world_

### Chip Components

```
┌─────────────────────────────────────────────────────────┐
│                        CHIP                             │
├─────────────────────────────────────────────────────────┤
│  IDENTITY      │ Who is this chip? What domain?        │
├─────────────────────────────────────────────────────────┤
│  TRIGGERS      │ What events activate this chip?       │
├─────────────────────────────────────────────────────────┤
│  OBSERVERS     │ When active, what data to capture?    │
├─────────────────────────────────────────────────────────┤
│  LEARNERS      │ What patterns/correlations to find?   │
├─────────────────────────────────────────────────────────┤
│  OUTCOMES      │ What does success/failure look like?  │
├─────────────────────────────────────────────────────────┤
│  EVOLUTION     │ How does this chip improve itself?    │
└─────────────────────────────────────────────────────────┘
```

Guardrails (required fields in `chip`):

- human_benefit
- harm_avoidance
- risk_level (low/medium/high)
- safety_tests

---

## Architecture Overview

### Current Spark (Monolithic)

```
Events → Queue → Pattern Detection → Cognitive Insights → Context Sync
                        │
              (hardcoded detectors)
              - CorrectionDetector
              - SentimentDetector
              - RepetitionDetector
              - SemanticIntentDetector
```

### Spark with Chips (Pluggable)

```
Events → Queue → Chip Router ─────────────────────────────────→ Context Sync
                     │                                              ↑
         ┌───────────┼───────────────────┐                          │
         ▼           ▼                   ▼                          │
   ┌──────────┐ ┌──────────┐      ┌──────────┐                     │
   │   Core   │ │Marketing │ ...  │  Sales   │                     │
   │   Chip   │ │   Chip   │      │   Chip   │                     │
   └────┬─────┘ └────┬─────┘      └────┬─────┘                     │
        │            │                  │                          │
        ▼            ▼                  ▼                          │
   ┌─────────────────────────────────────────┐                     │
   │           Chip Insights Store           │─────────────────────┘
   │   (namespaced by chip, domain-specific) │
   └─────────────────────────────────────────┘
```

### Integration Points

| Spark Component          | How Chips Integrate                                                       |
| ------------------------ | ------------------------------------------------------------------------- |
| **Queue (events.jsonl)** | Chips subscribe to event types via triggers                               |
| **Pattern Detection**    | Core chip = existing detectors; other chips add domain-specific detection |
| **Cognitive Learner**    | Chips have namespaced insight stores                                      |
| **Outcome Log**          | Chips define domain-specific outcomes                                     |
| **Validation Loop**      | Chips validate their own predictions                                      |
| **Bridge Worker**        | Iterates over active chips each cycle                                     |
| **Context Sync**         | Chips contribute domain-specific context                                  |

---

## Chip Specification Format

### Complete Example: Marketing Chip

```yaml
# ~/.spark/chips/marketing.chip.yaml

# ============================================================
# IDENTITY: Who is this chip?
# ============================================================
chip:
  id: marketing
  name: Marketing Intelligence
  version: 1.0.0
  description: |
    Makes Spark intelligent about marketing outcomes.
    Learns what campaigns work, which channels perform,
    what messaging resonates, and how to improve over time.

  author: Vibeship
  license: MIT

  # Humanity-first guardrails (required)
  human_benefit: "Improve marketing effectiveness without manipulation or harm."
  harm_avoidance:
    - "No deceptive or coercive messaging"
    - "No exploitation of vulnerable audiences"
  risk_level: medium
  safety_tests:
    - "no_deceptive_growth"
    - "no_harmful_targeting"

  # Domains this chip owns (for routing)
  domains:
    - marketing
    - campaigns
    - content
    - social-media
    - advertising
    - audience
    - engagement

# ============================================================
# TRIGGERS: What activates this chip?
# ============================================================
triggers:
  # Pattern-based triggers (match against event content)
  patterns:
    - "campaign"
    - "launched ad"
    - "published content"
    - "social post"
    - "email blast"
    - "audience segment"
    - "engagement rate"
    - "conversion"
    - "CTR"
    - "ROI"
    - "impressions"
    - "reach"

  # Event type triggers
  events:
    - marketing_campaign_launch
    - marketing_campaign_result
    - content_published
    - analytics_report

  # Tool triggers (when specific tools are used in marketing context)
  tools:
    - name: WebFetch
      context_contains: ["analytics", "campaign", "social"]
    - name: Bash
      context_contains: ["deploy", "publish", "post"]

# ============================================================
# OBSERVERS: What data to capture when triggered?
# ============================================================
observers:
  # Campaign Launch Observer
  - name: campaign_launch
    description: Captures when a marketing campaign is launched

    triggers:
      - "launched campaign"
      - "started ads"
      - "campaign live"

    capture:
      required:
        - campaign_name: "Name of the campaign"
        - channel: "Marketing channel (social, email, paid, organic)"

      optional:
        - budget: "Campaign budget"
        - audience: "Target audience description"
        - creative_type: "Type of creative (video, image, text)"
        - messaging_tone: "Tone of messaging (professional, casual, urgent)"
        - start_date: "Campaign start date"
        - goals: "Campaign goals (awareness, conversion, engagement)"

    # How to extract these fields from events
    extraction:
      - field: campaign_name
        patterns:
          - 'campaign[:\s]+["\']?([^"\']+)["\']?'
          - 'launched[:\s]+["\']?([^"\']+)["\']?'

      - field: channel
        keywords:
          facebook: ["facebook", "fb", "meta"]
          instagram: ["instagram", "ig"]
          twitter: ["twitter", "x.com"]
          linkedin: ["linkedin"]
          email: ["email", "newsletter", "mailchimp"]
          google: ["google ads", "adwords", "ppc"]
          tiktok: ["tiktok"]
          organic: ["organic", "seo", "blog"]

  # Campaign Result Observer
  - name: campaign_result
    description: Captures campaign performance outcomes

    triggers:
      - "campaign results"
      - "ROI"
      - "conversion rate"
      - "campaign performance"
      - "analytics report"

    capture:
      required:
        - campaign_name: "Which campaign"
        - outcome_type: "positive/negative/neutral"

      optional:
        - roi: "Return on investment"
        - conversions: "Number of conversions"
        - cpa: "Cost per acquisition"
        - ctr: "Click-through rate"
        - engagement_rate: "Engagement rate"
        - reach: "Total reach"
        - impressions: "Total impressions"
        - revenue: "Revenue generated"
        - cost: "Total cost"

  # Content Performance Observer
  - name: content_performance
    description: Tracks individual content piece performance

    triggers:
      - "post performed"
      - "content analytics"
      - "engagement"

    capture:
      required:
        - content_type: "Type of content"
        - platform: "Where it was published"

      optional:
        - engagement: "Engagement metrics"
        - shares: "Share count"
        - comments: "Comment count"
        - saves: "Save count"
        - topic: "Content topic"
        - format: "Content format"

# ============================================================
# LEARNERS: What patterns to detect and learn?
# ============================================================
learners:
  # Channel Effectiveness Learner
  - name: channel_effectiveness
    description: Learns which channels perform best for different goals
    type: correlation

    input:
      observer: campaign_launch
      fields: [channel, audience, goals]

    output:
      observer: campaign_result
      fields: [roi, conversions, engagement_rate]

    learn:
      - "Which channels produce highest ROI"
      - "Which channels work best for each audience"
      - "Channel performance trends over time"

    min_samples: 5  # Need at least 5 data points
    confidence_threshold: 0.7

  # Messaging Effectiveness Learner
  - name: messaging_effectiveness
    description: Learns what messaging resonates with audiences
    type: pattern

    observe: high_performing_content

    extract:
      - common_topics
      - effective_tones
      - optimal_length
      - best_formats

    correlate_with:
      - audience_segment
      - platform
      - time_of_day

  # Timing Learner
  - name: optimal_timing
    description: Learns best times to publish/launch
    type: correlation

    input:
      fields: [start_date, publish_time, day_of_week]

    output:
      fields: [engagement_rate, reach, conversions]

    learn:
      - "Best days to launch campaigns"
      - "Optimal posting times per platform"
      - "Seasonal patterns"

  # Budget Efficiency Learner
  - name: budget_efficiency
    description: Learns optimal budget allocation
    type: optimization

    input:
      fields: [budget, channel, campaign_duration]

    output:
      fields: [roi, cpa, revenue]

    optimize_for: maximize_roi
    constraints:
      - min_roi: 1.0
      - max_cpa: target_cpa

# ============================================================
# OUTCOMES: What does success/failure look like?
# ============================================================
outcomes:
  # Positive outcomes (success signals)
  positive:
    - condition: "roi > 2.0"
      weight: 1.0
      insight: "High ROI campaign"

    - condition: "cpa < target_cpa * 0.8"
      weight: 0.8
      insight: "Efficient acquisition"

    - condition: "engagement_rate > industry_benchmark * 1.5"
      weight: 0.7
      insight: "Above-average engagement"

    - condition: "conversions > goal"
      weight: 0.9
      insight: "Goal exceeded"

  # Negative outcomes (failure signals)
  negative:
    - condition: "roi < 0.5"
      weight: 1.0
      insight: "Campaign underperformed"
      action: analyze_failure

    - condition: "budget_exhausted_early AND low_conversions"
      weight: 0.9
      insight: "Budget burned without results"
      action: review_targeting

    - condition: "engagement_rate < industry_benchmark * 0.5"
      weight: 0.7
      insight: "Poor engagement"
      action: review_creative

  # Neutral (learning opportunities)
  neutral:
    - condition: "new_channel_tested"
      insight: "Establishing baseline for new channel"
      action: start_learning

# ============================================================
# EVOLUTION: How does this chip improve itself?
# ============================================================
evolution:
  # Automatic evolution rules
  rules:
    # When predictions are wrong, expand what we observe
    - trigger:
        condition: "prediction_accuracy < 60%"
        over: "last_20_predictions"

      action: expand_observation
      details:
        add_fields: [audience_size, competitor_activity, market_conditions]
        reason: "Low accuracy suggests missing variables"

    # When a pattern is validated many times, increase its weight
    - trigger:
        condition: "pattern_validated >= 10"

      action: boost_pattern
      details:
        increase_weight: 0.2
        promote_to: high_confidence

    # When a learner has enough data, try more complex correlations
    - trigger:
        condition: "sample_count >= 50"
        learner: channel_effectiveness

      action: upgrade_learner
      details:
        enable: multi_variable_correlation
        add_dimensions: [seasonality, audience_segment]

    # Prune learners that don't produce insights
    - trigger:
        condition: "insights_generated == 0"
        over: "last_30_days"
        learner: "*"

      action: disable_learner
      details:
        reason: "No insights generated"
        notify: true

    # When new pattern detected, create ad-hoc learner
    - trigger:
        condition: "unknown_pattern_detected"

      action: create_exploratory_learner
      details:
        duration: "14_days"
        auto_promote_if: "generates_3_validated_insights"

  # Self-improvement metrics
  metrics:
    track:
      - prediction_accuracy
      - insight_quality  # Based on validation
      - outcome_coverage  # % of outcomes we can explain
      - learning_velocity  # New insights per week

    goals:
      prediction_accuracy: "> 75%"
      insight_quality: "> 80% validated"
      outcome_coverage: "> 60%"
      learning_velocity: "> 2 per week"

# ============================================================
# CONTEXT CONTRIBUTION: What does this chip add to context?
# ============================================================
context:
  # What to include in SPARK_CONTEXT.md / CLAUDE.md
  format: |
    ## Marketing Intelligence (Chip: marketing)

    ### Channel Performance
    {{#each channel_insights}}
    - {{channel}}: {{performance}} ({{confidence}}% confident)
    {{/each}}

    ### Recent Learnings
    {{#each recent_insights limit=5}}
    - {{insight}}
    {{/each}}

    ### Predictions
    {{#each active_predictions}}
    - {{prediction}} ({{confidence}}%)
    {{/each}}

  # Priority (higher = included first if space limited)
  priority: 0.8

  # Max characters
  max_chars: 800

# ============================================================
# INTEGRATIONS: External data sources
# ============================================================
integrations:
  optional:
    - name: google_analytics
      type: api
      purpose: "Pull real campaign metrics"

    - name: meta_ads
      type: api
      purpose: "Pull Facebook/Instagram ad performance"

    - name: hubspot
      type: api
      purpose: "Pull email campaign metrics"

  # Integrations enhance the chip but aren't required
  # Chip works with manual input if integrations unavailable
```

---

## Real-World Use Cases

### 1. Marketing Team (Small Business)

**Scenario:** A 5-person marketing team runs campaigns across social media, email, and paid ads. They want to learn what works.

**Chip:** `marketing.chip.yaml` (above)

**What Spark Learns:**

- "Instagram Stories with user testimonials get 3x more engagement than product shots"
- "Email campaigns sent Tuesday 10am have 40% higher open rates"
- "Paid ads targeting 'small business owners' convert at 2x the rate of 'entrepreneurs'"

**Value:** The team stops guessing. Spark tells them what's actually working based on their specific audience.

---

### 2. Sales Team (B2B SaaS)

**Scenario:** A 20-person sales team closes enterprise deals. They want to understand what predicts success.

**Chip:** `sales-b2b.chip.yaml`

```yaml
chip:
  id: sales-b2b
  name: B2B Sales Intelligence
  description: Learns patterns in B2B sales cycles

triggers:
  patterns:
    - "deal"
    - "prospect"
    - "demo"
    - "proposal"
    - "objection"
    - "close"
    - "pipeline"
    - "champion"
    - "decision maker"

observers:
  - name: deal_progress
    capture:
      - deal_id
      - stage_from
      - stage_to
      - days_in_stage
      - champion_identified
      - decision_maker_engaged
      - objections_raised

  - name: deal_outcome
    capture:
      - deal_id
      - won_lost
      - deal_size
      - sales_cycle_days
      - close_reason
      - competitor_mentioned

learners:
  - name: win_predictors
    type: correlation
    learn:
      - "Early champion identification correlates with 3x win rate"
      - "Deals stalled in 'evaluation' > 30 days have 20% close rate"
      - "Multi-threading (3+ contacts) increases win rate by 50%"

  - name: objection_handling
    type: pattern
    observe: objection → response → outcome
    learn: "Which responses overcome which objections"

outcomes:
  positive:
    - condition: "deal_won"
    - condition: "deal_size > average"
    - condition: "sales_cycle < average"

  negative:
    - condition: "deal_lost"
    - condition: "deal_stalled > 60 days"
    - condition: "price_objection_not_overcome"

evolution:
  rules:
    - trigger: "new_objection_detected"
      action: start_tracking_responses

    - trigger: "win_rate_prediction_off > 20%"
      action: add_observation_fields
```

**What Spark Learns:**

- "Deals with a technical champion close 3x faster"
- "When 'budget concerns' raised, offering a pilot converts 60% of stalled deals"
- "Deals touching 4+ stakeholders have 80% win rate vs 30% for single-threaded"

---

### 3. Engineering Team (Startup)

**Scenario:** A 15-person engineering team ships features weekly. They want to reduce bugs and improve velocity.

**Chip:** `engineering-velocity.chip.yaml`

```yaml
chip:
  id: engineering-velocity
  name: Engineering Velocity Intelligence
  description: Learns patterns in code quality and delivery speed

triggers:
  patterns:
    - "deploy"
    - "bug"
    - "regression"
    - "PR"
    - "code review"
    - "refactor"
    - "test"
    - "incident"
    - "hotfix"

observers:
  - name: code_change
    capture:
      - files_changed
      - lines_added
      - lines_removed
      - change_type # feature, bugfix, refactor
      - author
      - review_time
      - test_coverage_delta

  - name: deployment
    capture:
      - version
      - deploy_time
      - rollback_needed
      - incidents_within_24h

  - name: incident
    capture:
      - severity
      - time_to_detect
      - time_to_resolve
      - root_cause
      - related_change

learners:
  - name: risky_changes
    type: pattern
    observe: code_changes → incidents
    learn:
      - "Changes to auth/ directory have 5x incident rate"
      - "PRs > 500 lines have 3x more bugs"
      - "Changes without tests have 4x rollback rate"

  - name: velocity_factors
    type: correlation
    input: [team_size, sprint_load, tech_debt_score]
    output: [features_shipped, bug_rate]
    learn: "What affects team velocity"

outcomes:
  positive:
    - condition: "deployed AND no_incidents_24h"
    - condition: "bug_fixed AND no_regression"
    - condition: "feature_shipped AND positive_feedback"

  negative:
    - condition: "rollback_needed"
    - condition: "incident_caused"
    - condition: "deadline_missed"
```

**What Spark Learns:**

- "PRs reviewed by @alice have 50% fewer bugs"
- "Deploys on Friday have 3x incident rate — avoid"
- "Features touching the billing module need extra testing"

---

### 4. Factory Operations (Manufacturing)

**Scenario:** A factory with 200 workers produces widgets. They want to optimize quality and reduce downtime.

**Chip:** `manufacturing-ops.chip.yaml`

```yaml
chip:
  id: manufacturing-ops
  name: Manufacturing Operations Intelligence
  description: Learns patterns in production quality and efficiency

triggers:
  patterns:
    - "production"
    - "quality"
    - "defect"
    - "downtime"
    - "maintenance"
    - "shift"
    - "batch"
    - "yield"
    - "scrap"

observers:
  - name: production_run
    capture:
      - batch_id
      - product_type
      - machine_id
      - operator_id
      - shift
      - start_time
      - end_time
      - units_produced
      - defect_count
      - scrap_rate

  - name: machine_event
    capture:
      - machine_id
      - event_type # start, stop, maintenance, breakdown
      - duration
      - cause

  - name: quality_check
    capture:
      - batch_id
      - passed
      - defect_types
      - inspector_id

learners:
  - name: defect_predictors
    type: correlation
    input:
      [machine_id, operator_id, shift, material_batch, temperature, humidity]
    output: [defect_rate, scrap_rate]
    learn:
      - "Machine #7 after 4 hours continuous run increases defects 40%"
      - "Night shift has 20% higher defect rate — fatigue factor"
      - "Material from Supplier B has 2x defect rate"

  - name: maintenance_optimization
    type: pattern
    observe: machine_metrics → breakdown
    learn: "Predict maintenance needs before breakdown"

outcomes:
  positive:
    - condition: "batch_passed_qa AND defect_rate < 1%"
    - condition: "uptime > 95%"
    - condition: "yield > target"

  negative:
    - condition: "batch_rejected"
    - condition: "unplanned_downtime"
    - condition: "scrap_rate > 5%"

evolution:
  rules:
    - trigger: "defect_spike_detected"
      action: expand_observation
      details:
        add_fields: [temperature, humidity, material_lot]

    - trigger: "breakdown_not_predicted"
      action: add_sensors
      details:
        recommend: [vibration, temperature, noise]
```

**What Spark Learns:**

- "Machine #3 needs maintenance when vibration exceeds 0.5g — prevents 80% of breakdowns"
- "Operator training program reduced defects 35%"
- "Material from Supplier A + Machine #7 = optimal quality"

---

### 5. CEO Dashboard (Enterprise)

**Scenario:** CEO of a 500-person company wants high-level intelligence across all departments.

**Chip:** `executive-intelligence.chip.yaml`

```yaml
chip:
  id: executive
  name: Executive Intelligence
  description: Cross-functional insights for leadership decisions

triggers:
  patterns:
    - "revenue"
    - "growth"
    - "churn"
    - "headcount"
    - "runway"
    - "OKR"
    - "board"
    - "investor"
    - "strategic"

observers:
  - name: business_metric
    capture:
      - metric_name
      - value
      - period
      - trend # up, down, flat
      - vs_target

  - name: strategic_decision
    capture:
      - decision
      - rationale
      - expected_outcome
      - owner
      - deadline

  - name: decision_outcome
    capture:
      - decision_id
      - actual_outcome
      - variance_from_expected
      - lessons

learners:
  - name: leading_indicators
    type: correlation
    learn:
      - "NPS drop precedes churn spike by 60 days"
      - "Engineering velocity drop predicts feature delays 2 sprints ahead"
      - "Sales pipeline < 3x target predicts missed quarter"

  - name: decision_quality
    type: pattern
    observe: strategic_decisions → outcomes
    learn: "Which decision patterns lead to good outcomes"

outcomes:
  positive:
    - condition: "revenue_growth > plan"
    - condition: "decision_outcome > expected"
    - condition: "strategic_goal_achieved"

  negative:
    - condition: "revenue_miss"
    - condition: "churn_spike"
    - condition: "strategic_pivot_needed"
```

**What Spark Learns:**

- "Decisions made with data take 2x longer but succeed 3x more often"
- "Q4 always underperforms projections by 15% — adjust forecasts"
- "Acquisitions proposed by BD team have 30% success rate vs 70% from product team"

---

### 6. Customer Support (High Volume)

**Scenario:** Support team handles 1000+ tickets/day. They want to reduce resolution time and improve satisfaction.

**Chip:** `support-intelligence.chip.yaml`

```yaml
chip:
  id: support
  name: Customer Support Intelligence
  description: Learns patterns in support efficiency and satisfaction

triggers:
  patterns:
    - "ticket"
    - "support"
    - "customer"
    - "issue"
    - "resolution"
    - "escalation"
    - "CSAT"
    - "NPS"

observers:
  - name: ticket
    capture:
      - ticket_id
      - category
      - priority
      - customer_tier
      - agent_id
      - first_response_time
      - resolution_time
      - escalated
      - csat_score

  - name: resolution
    capture:
      - ticket_id
      - resolution_type # solved, workaround, feature_request, wont_fix
      - solution_used
      - reopen_count

learners:
  - name: resolution_patterns
    type: pattern
    observe: issue_type → solution → satisfaction
    learn:
      - "Billing issues resolved with refund have 95% CSAT"
      - "Technical issues need escalation 40% of time — training gap"
      - "Response within 1 hour = 20% higher CSAT"

  - name: agent_effectiveness
    type: correlation
    input: [agent_id, ticket_category, customer_tier]
    output: [resolution_time, csat_score, reopen_rate]
    learn: "Which agents excel at which issue types"

outcomes:
  positive:
    - condition: "csat >= 4"
    - condition: "resolution_time < target"
    - condition: "no_reopen"

  negative:
    - condition: "csat <= 2"
    - condition: "escalation_needed"
    - condition: "ticket_reopened"
```

**What Spark Learns:**

- "Agent Sarah resolves billing issues 40% faster than average"
- "Integration issues from Enterprise customers need engineering escalation 80% of time"
- "Proactive status updates reduce escalations by 50%"

---

### 7. Research Team (R&D Lab)

**Scenario:** Research team runs experiments and tests hypotheses. They want to learn from failures and successes.

**Chip:** `research-intelligence.chip.yaml`

```yaml
chip:
  id: research
  name: Research Intelligence
  description: Learns patterns in research outcomes and hypothesis validation

triggers:
  patterns:
    - "experiment"
    - "hypothesis"
    - "result"
    - "significant"
    - "p-value"
    - "control"
    - "variable"

observers:
  - name: experiment
    capture:
      - experiment_id
      - hypothesis
      - methodology
      - variables
      - sample_size
      - duration

  - name: result
    capture:
      - experiment_id
      - outcome # confirmed, rejected, inconclusive
      - effect_size
      - confidence
      - unexpected_findings

learners:
  - name: methodology_effectiveness
    type: correlation
    learn: "Which methodologies produce reliable results"

  - name: hypothesis_patterns
    type: pattern
    observe: hypothesis_type → outcome
    learn: "Which types of hypotheses tend to be confirmed/rejected"

outcomes:
  positive:
    - condition: "hypothesis_confirmed AND replicable"
    - condition: "unexpected_finding_valuable"

  negative:
    - condition: "experiment_invalidated"
    - condition: "result_not_replicable"
```

---

### 8. Personal Productivity (Individual)

**Scenario:** A solo professional wants Spark to learn their personal productivity patterns.

**Chip:** `personal-productivity.chip.yaml`

```yaml
chip:
  id: personal
  name: Personal Productivity Intelligence
  description: Learns your personal work patterns and optimizes your day

triggers:
  patterns:
    - "task"
    - "todo"
    - "deadline"
    - "meeting"
    - "focus"
    - "break"
    - "energy"

observers:
  - name: work_session
    capture:
      - task_type
      - start_time
      - duration
      - completed
      - interruptions
      - energy_level

  - name: day_review
    capture:
      - tasks_planned
      - tasks_completed
      - biggest_win
      - biggest_blocker

learners:
  - name: optimal_schedule
    type: correlation
    learn:
      - "Deep work best between 9-11am"
      - "Meetings after 2pm have lower engagement"
      - "Creative tasks better on Tuesday/Wednesday"

  - name: energy_patterns
    type: pattern
    learn: "What drains vs energizes you"

outcomes:
  positive:
    - condition: "task_completed_on_time"
    - condition: "deep_work_session > 2_hours"

  negative:
    - condition: "deadline_missed"
    - condition: "burnout_signals"
```

---

## Chip Ecosystem Architecture

### Directory Structure

```
~/.spark/
├── chips/
│   ├── registry.json         # Installed chips metadata
│   ├── active.json           # Currently active chips
│   │
│   ├── official/             # Bundled with Spark
│   │   ├── core.chip.yaml    # Default Spark learning
│   │   └── engineering.chip.yaml
│   │
│   ├── community/            # Downloaded from hub
│   │   ├── marketing.chip.yaml
│   │   ├── sales-b2b.chip.yaml
│   │   └── ...
│   │
│   └── custom/               # User-created
│       └── my-company.chip.yaml
│
├── chip_insights/            # Per-chip insight storage
│   ├── marketing/
│   │   ├── insights.json
│   │   ├── predictions.jsonl
│   │   └── outcomes.jsonl
│   │
│   └── sales-b2b/
│       └── ...
│
└── chip_evolution/           # Chip self-modification logs
    ├── marketing_evolution.jsonl
    └── ...
```

### Chip Registry (registry.json)

```json
{
  "chips": {
    "core": {
      "id": "core",
      "name": "Core Intelligence",
      "version": "1.0.0",
      "source": "official",
      "installed_at": "2024-01-15T10:30:00Z",
      "active": true
    },
    "marketing": {
      "id": "marketing",
      "name": "Marketing Intelligence",
      "version": "1.2.0",
      "source": "community",
      "installed_at": "2024-01-20T14:00:00Z",
      "active": true,
      "stats": {
        "insights_generated": 47,
        "predictions_made": 123,
        "prediction_accuracy": 0.72,
        "evolutions": 3
      }
    }
  }
}
```

### Chip Hub (Future)

A community repository for sharing chips:

```
spark-chip-hub/
├── categories/
│   ├── business/
│   │   ├── marketing/
│   │   ├── sales/
│   │   ├── finance/
│   │   └── operations/
│   │
│   ├── engineering/
│   │   ├── velocity/
│   │   ├── quality/
│   │   ├── devops/
│   │   └── security/
│   │
│   ├── personal/
│   │   ├── productivity/
│   │   ├── health/
│   │   └── learning/
│   │
│   └── industry/
│       ├── manufacturing/
│       ├── healthcare/
│       ├── finance/
│       └── retail/
```

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1-2)

- [ ] Chip specification parser (YAML → Python objects)
- [ ] Chip loader and registry
- [ ] Basic trigger matching
- [ ] Integration with existing event queue

### Phase 2: Observers & Learners (Week 3-4)

- [ ] Observer execution engine
- [ ] Field extraction from events
- [ ] Basic correlation learner
- [ ] Pattern matching learner
- [ ] Per-chip insight storage

### Phase 3: Outcomes & Validation (Week 5-6)

- [ ] Outcome definition parsing
- [ ] Outcome detection and logging
- [ ] Chip-specific prediction/validation loop
- [ ] Accuracy tracking per chip

### Phase 4: Evolution (Week 7-8)

- [ ] Evolution rule execution
- [ ] Self-modification capabilities
- [ ] Evolution logging and rollback
- [ ] Chip health metrics

### Phase 5: Ecosystem (Week 9-10)

- [ ] Chip export/import
- [ ] Version management
- [ ] Chip composition (chips using other chips)
- [ ] Community hub integration

---

## Mediumweight v1 Implementation (Guidance)

This section is the practical target for the first "mediumweight" chips system.
It is heavier than a pure YAML parser, but lighter than a full ML platform.

### 1) Hard-required event schema (small but enforced)

- Require SparkEventV1 fields (v, source, kind, ts, session_id, payload).
- Validate JSON shape and types before any chip executes.
- Treat schema violations as soft errors (log + skip), not fatal.

### 2) Extraction library + validators (avoid regex fragility)

- Provide a small extraction DSL and keyword maps.
- Allow structured extraction in addition to regex (key paths, enums, lookups).
- Built-in validators for required fields, types, ranges, and enum values.

### 3) Prediction -> Outcome linking

- Every prediction includes a stable prediction_id.
- Outcomes link via time window + entity refs (repo, PR, issue, incident, deploy).
- Maintain a thin matching layer (time window, entity refs, optional semantic text).

### 4) Chip permissions + data scopes

- Chips declare scopes for the data they need (events, MCPs, integrations).
- Default to least-privilege: deny scopes unless explicitly enabled.
- Community chips must be opt-in per scope.

### 5) Replay + evaluation (show value quickly)

- Run chip replay against a saved event log.
- Compute precision, recall, and outcome-coverage for each chip.
- Output a readable report to make ROI obvious.

### 6) CLI and packaging (spark-chips repo)

- `spark chips validate` to lint spec and check permissions.
- `spark chips run` and `spark chips replay` for local testing.
- Chips can be installed from file, URL, or registry.

### Repo boundary note

- Spark core stays stable and minimal.
- The chips runtime lives in the `vibeship-spark-chips` repo.
- Spark core depends on a thin compatibility shim (loader + router hooks).

---

## Vibecoding Chip (v1) Overview

This is the first reference chip. It is focused on engineering and "vibe coding"
signals across code, tooling, delivery, and outcomes. The full spec is defined in
the chip schema and operational guidelines.

### MCP profiles and categories (v1)

- VibeShip: Idearalph, Mind, Spawner, Scanner, Suparalph, Knowledge Base.
- Repo / PR / diff / review signals.
- CI / tests / coverage signals.
- Deploy / release signals.
- Runtime / observability signals.
- Product analytics signals.
- Design / UX signals.
- Support / feedback signals.

### Primary outcomes (examples)

- PR merged without rollback within N days.
- CI failures decreased after a fix.
- Production error rate or latency improved after a change.
- Incident resolved with a documented prevention.

---

## API Reference

### Chip CLI Commands

```bash
# List installed chips
spark chips list

# Install a chip
spark chips install marketing.chip.yaml
spark chips install https://spark-hub.io/chips/sales-b2b

# Activate/deactivate
spark chips activate marketing
spark chips deactivate marketing

# Check chip status
spark chips status marketing

# View chip insights
spark chips insights marketing --limit 10

# Trigger chip evolution
spark chips evolve marketing

# Export chip with learned data
spark chips export marketing --include-insights

# Create new chip from template
spark chips create my-chip --template business
```

### Chip Python API

```python
from spark.chips import ChipLoader, ChipRunner

# Load a chip
loader = ChipLoader()
marketing_chip = loader.load("~/.spark/chips/marketing.chip.yaml")

# Run chip on an event
runner = ChipRunner(marketing_chip)
insights = runner.process_event({
    "type": "marketing_event",
    "content": "Launched Q4 campaign on Instagram, budget $5000",
    "timestamp": "2024-01-15T10:00:00Z"
})

# Get chip predictions
predictions = runner.get_predictions()

# Record outcome
runner.record_outcome({
    "campaign": "Q4 Instagram",
    "roi": 2.5,
    "conversions": 150
})

# Trigger evolution check
evolutions = runner.check_evolution()
```

---

## Design Principles

### 1. Progressive Complexity

- Simple chips work with minimal configuration
- Advanced features (evolution, integrations) are optional
- Start capturing data, add learners later

### 2. Graceful Degradation

- Chips work without external integrations
- Missing fields don't break observation
- Partial data still generates insights

### 3. Transparency

- All chip decisions are logged
- Evolution changes are reversible
- Users can inspect/override any learning

### 4. Composability

- Chips can reference other chips
- Insights from one chip can trigger another
- Build complex intelligence from simple pieces

### 5. Privacy First

- Chips define what data to capture explicitly
- No hidden data collection
- User controls what leaves their machine

---

## Glossary

| Term           | Definition                                                          |
| -------------- | ------------------------------------------------------------------- |
| **Chip**       | A YAML specification that teaches Spark how to learn about a domain |
| **Trigger**    | A pattern or event that activates a chip                            |
| **Observer**   | A component that captures data when triggered                       |
| **Learner**    | A component that extracts patterns/correlations from observed data  |
| **Outcome**    | A definition of what success/failure looks like                     |
| **Evolution**  | Rules for how a chip improves itself over time                      |
| **Insight**    | A learned pattern or correlation                                    |
| **Prediction** | A forecast based on learned patterns                                |
| **Validation** | Checking if predictions match actual outcomes                       |

---

## FAQ

**Q: How is this different from just writing code?**
A: Chips are declarative specifications. You describe _what_ to learn, not _how_ to learn it. Spark handles the learning mechanics. This makes chips accessible to non-programmers and consistent across domains.

**Q: Can chips conflict with each other?**
A: Chips are namespaced. Each chip has its own insight store. If multiple chips trigger on the same event, each processes it independently. Future versions may support chip coordination.

**Q: What if my domain isn't covered?**
A: Create a custom chip! The YAML format is designed to be readable and writable by humans. Start with a template and customize.

**Q: How do chips evolve safely?**
A: All evolution is logged. Chips can only modify themselves within defined bounds. Users can review and rollback any evolution. Critical changes require user approval.

**Q: Can I use chips without an LLM?**
A: Yes. Chips work at the Spark layer, which is LLM-agnostic. The insights chips generate can enhance any AI assistant (Claude, GPT, Gemini, local models, etc.).

---

## Next Steps

1. **Read the examples** — See how chips work for different domains
2. **Install a chip** — Try the marketing or engineering chip
3. **Create your own** — Use the template to build a custom chip
4. **Share your chip** — Contribute to the community hub

---

_Spark Chips: Teaching AI how to think about your world._
