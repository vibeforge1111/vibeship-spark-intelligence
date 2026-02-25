# Spark Intelligence — Kanban Dashboard (Analyzable)

Updated: 2026-02-25
Board Type: Execution + KPI-linked

## Scoring Model
- **Impact (1-10)**: Expected business/system value
- **Urgency (1-10)**: Time criticality
- **Risk Reduction (1-10)**: Stability/safety gain
- **Effort (1-13)**: Relative complexity points
- **Priority Score** = `(Impact + Urgency + Risk Reduction) / Effort`

## KPI Targets (Board-Level)
1. Memory capture noise ratio: **0.356 -> <=0.20**
2. Context p50 chars: **53 -> >=120**
3. Advisory emit rate: **0.076 -> >=0.20** (without noise regression)
4. Semantic low-sim ratio (<0.1): **0.235 -> <=0.15**
5. Metric drift incidents/day: **>1 -> <=1**

---

## Column: IN_PROGRESS

| ID | Task | Goal/Intent | KPI Link | Baseline | Target | Impact | Urgency | Risk Red. | Effort | Priority Score |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| CB-004 | Capture noise filtering | Stop low-value memory ingress | Noise ratio | 0.356 | 0.20 | 10 | 9 | 10 | 5 | 5.8 |
| CB-005 | Context window uplift | Preserve condition-action-reason in memory | Context p50 | 53 | 120 | 9 | 8 | 8 | 5 | 5.0 |
| CB-006 | Threshold calibration | Improve precision-first memory capture | Noise + miss balance | 0.356 | <=0.25 short-term | 8 | 7 | 8 | 5 | 4.6 |
| CB-007 | Daily memory observatory | Make memory quality measurable every day | Daily grade | RED 0.586 | YELLOW->GREEN | 9 | 9 | 9 | 3 | 9.0 |
| CB-030 | 5-section nightly self-interrogation | Continuous optimization loop | Daily action quality | ad-hoc | systematic | 8 | 8 | 8 | 2 | 12.0 |

---

## Column: READY (Next Up)

| ID | Task | Goal/Intent | KPI Link | Baseline | Target | Impact | Urgency | Risk Red. | Effort | Priority Score |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| CB-009 | Suppression cause audit | Identify over-suppression drivers | Emit rate, noise | 0.076 emit | >=0.14 phase-1 | 10 | 9 | 9 | 3 | 9.3 |
| CB-010 | Dedupe policy tuning | Restore useful emission while keeping quality | Emit + noise burden | 0.076 / 0.744 | >=0.20 / <=0.65 | 10 | 9 | 10 | 8 | 3.6 |
| CB-019 | Observatory Operator-Now block | Make top actions visible instantly | Triage time | >5 min | <90 sec | 8 | 8 | 8 | 3 | 8.0 |
| CB-020 | Memory quality in flow health | Expose memory risk in main observatory | Memory visibility | absent | present | 7 | 7 | 7 | 2 | 10.5 |
| CB-023 | Pulse dead-widget cleanup | Remove misleading empty panes | Operator trust | low | high | 8 | 8 | 8 | 3 | 8.0 |
| CB-024 | Pulse endpoint rewiring | Use existing live data where available | Dashboard utility | partial | full core | 9 | 9 | 8 | 5 | 5.2 |
| CB-027 | Cross-surface drift checker | Detect metric inconsistencies daily | Drift/day | >1 | <=1 | 9 | 8 | 10 | 5 | 5.4 |

---

## Column: BACKLOG

| ID | Task | Goal/Intent | KPI Link | Impact | Urgency | Risk Red. | Effort | Priority Score |
|---|---|---|---|---:|---:|---:|---:|---:|
| CB-014 | Onboarding telemetry instrumentation | Measure funnel/dropoff/TTFV clearly | Onboarding success | 9 | 8 | 8 | 8 | 3.1 |
| CB-015 | Progressive onboarding flow spec | Reduce first-run friction | TTFV + completion | 8 | 7 | 7 | 8 | 2.8 |
| CB-016 | Error→remediation map | Make failures actionable | Recovery rate | 8 | 7 | 8 | 5 | 4.6 |
| CB-017 | LLM lane UX strategy | Make provider selection practical | Config success rate | 7 | 6 | 7 | 8 | 2.5 |
| CB-018 | Onboard verify contract | Pass/fail confidence for setup | 1st-try success | 8 | 7 | 8 | 8 | 2.9 |
| CB-021 | Observatory regression ledger | Single source for regressions | Regression MTTR | 7 | 6 | 8 | 3 | 7.0 |
| CB-022 | Metric contract page | Align metric definitions | Drift + trust | 8 | 7 | 9 | 5 | 4.8 |
| CB-025 | Pulse no-BS mode | Operator-focused critical view | Decision latency | 8 | 7 | 8 | 5 | 4.6 |
| CB-026 | Pulse next-action hints | Every red metric actionable | Fix velocity | 7 | 6 | 8 | 5 | 4.2 |
| CB-028 | Resolve drift mismatches | Reduce contradictions across surfaces | Drift/day | 9 | 8 | 10 | 8 | 3.4 |
| CB-029 | Confidence/freshness labels | Improve metric trustworthiness | Trust index | 7 | 6 | 7 | 3 | 6.7 |
| CB-031 | Daily top-5 actions with owners | Enforce execution discipline | Task completion | 8 | 8 | 8 | 2 | 12.0 |
| CB-032 | 48h escalation protocol | Prevent stalled red items | Red age | 7 | 7 | 9 | 2 | 11.5 |
| CB-033 | Weekly SOTA delta review | Keep trajectory aligned to frontier | Weekly maturity | 7 | 6 | 8 | 3 | 7.0 |

---

## Column: BLOCKED

| ID | Task | Blocker | Unblock Condition |
|---|---|---|---|
| (none) | — | — | — |

---

## Column: DONE

| ID | Task | Outcome |
|---|---|---|
| CB-030 (partial setup) | Nightly report structure and interrogation prompts | Scheduled and active |
| Memory observability bootstrap | Daily memory observatory file/report generation | Implemented |

---

## Weekly Dashboard Readout (for updates)

- Completed this week:
- In-progress carryover:
- KPI movement:
  - Noise ratio:
  - Context p50:
  - Emit rate:
  - Low-sim ratio:
  - Drift/day:
- Biggest blocker:
- Next 5 tasks by priority score:
