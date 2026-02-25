# Spark Intelligence — Combat Board (Master)

Date started: 2026-02-25  
Mode: execution tracking  
Status legend: `QUEUED` / `READY` / `IN_PROGRESS` / `BLOCKED` / `DONE`

---

## Mission Goals (14-day)

1. Raise signal quality and cut memory noise.
2. Increase advisory usefulness without raising noise burden.
3. Make onboarding/web flow measurable and lower-friction.
4. Turn Observatory + Pulse into operator-useful control surfaces.
5. Enforce cross-surface metric coherence.

---

## Combat Board

| ID | Workstream | Task | Priority | Status | Owner | ETA | Dependencies | Definition of Done |
|---|---|---|---|---|---|---|---|---|
| CB-001 | Control/Baseline | Freeze baseline snapshots (memory, advisory, onboarding, observatory, pulse) | P0 | READY | Spark | D+0 | None | Baseline report file committed with timestamped metrics |
| CB-002 | Control/Baseline | Publish single KPI board with hard gates | P0 | READY | Spark | D+0 | CB-001 | One canonical KPI markdown/json with gate thresholds |
| CB-003 | Control/Baseline | Set 7-day and 14-day target ranges | P0 | READY | Spark | D+0 | CB-002 | Target table committed and referenced in nightly report |
| CB-004 | Memory | Enforce capture noise filtering at ingest | P0 | IN_PROGRESS | Spark | D+1 | CB-001 | Capture noise ratio trending down day-over-day |
| CB-005 | Memory | Expand/compact semantic context capture window | P0 | IN_PROGRESS | Spark | D+1 | CB-004 | Context p50 materially improved from baseline |
| CB-006 | Memory | Calibrate capture thresholds for precision-first mode | P0 | IN_PROGRESS | Spark | D+2 | CB-004 | Auto-save precision improves without major recall collapse |
| CB-007 | Memory | Daily memory observatory trend tracking | P0 | IN_PROGRESS | Spark | Daily | CB-001 | Daily snapshots + report generated automatically |
| CB-008 | Memory | Queue/backlog hygiene policy (drain + stale trim) | P1 | READY | Spark | D+3 | CB-007 | Backlog policy doc + measurable backlog reduction |
| CB-009 | Advisory | Suppression cause audit (ranked) | P0 | READY | Spark | D+2 | CB-001 | Top suppression reasons with ratios + evidence |
| CB-010 | Advisory | Dedupe policy calibration (reduce over-suppression) | P0 | READY | Spark | D+3 | CB-009 | Emit rate improved while noise burden stays within guardrail |
| CB-011 | Advisory | Actionability effectiveness metric (real outcome linked) | P1 | READY | Spark | D+4 | CB-009 | Metric exposed in daily report and tracked |
| CB-012 | Advisory | Packet freshness/readiness tightening plan | P1 | READY | Spark | D+4 | CB-009 | Freshness/readiness trend line upward |
| CB-013 | Advisory | Run controlled A/B gate variants | P1 | READY | Spark | D+5 | CB-010 | Decision report on best gate policy |
| CB-014 | Onboarding/Web | Instrument funnel telemetry (dropoff/TTFV/errors/recovery) | P0 | READY | Spark | D+4 | CB-001 | Telemetry schema and first populated daily sample |
| CB-015 | Onboarding/Web | Progressive onboarding flow plan (basic/guided/advanced) | P1 | READY | Spark | D+5 | CB-014 | Flow spec with screens and transitions |
| CB-016 | Onboarding/Web | Error-to-remediation mapping | P1 | READY | Spark | D+5 | CB-014 | Top errors mapped to actionable fixes |
| CB-017 | Onboarding/Web | LLM lane UX strategy (provider/budget/privacy) | P1 | READY | Spark | D+6 | CB-015 | Lane matrix and UX decision doc committed |
| CB-018 | Onboarding/Web | Onboard verify contract (score + pass/fail) | P1 | READY | Spark | D+6 | CB-014 | Verify contract defined and added to plan docs |
| CB-019 | Observatory | Add “Operator Now” block to flow front page | P0 | READY | Spark | D+3 | CB-002 | Top 3 blockers + next actions visible in flow page |
| CB-020 | Observatory | Surface memory quality card in front-page health | P0 | READY | Spark | D+3 | CB-007 | Memory quality visible in flow health table |
| CB-021 | Observatory | Add regression ledger page | P1 | READY | Spark | D+4 | CB-019 | Single page with regression owner/ETA/state |
| CB-022 | Observatory | Add metric contract page (definitions/formulas/source/freshness) | P1 | READY | Spark | D+5 | CB-002 | Contract page published and linked from flow |
| CB-023 | Pulse | Hide/degrade dead widgets by default | P0 | READY | Spark | D+3 | CB-001 | No dead pane shown as “healthy” |
| CB-024 | Pulse | Rewire LEARN/mission views to existing live endpoints | P0 | READY | Spark | D+4 | CB-023 | LEARN/mission populated with real data |
| CB-025 | Pulse | Add No-BS pulse mode (critical metrics only) | P1 | READY | Spark | D+5 | CB-024 | Operator mode view available |
| CB-026 | Pulse | Add per-metric “next action” hints | P1 | READY | Spark | D+6 | CB-025 | Each red metric shows actionable next step |
| CB-027 | Coherence | Cross-surface drift checker (CLI/Pulse/Observatory) | P0 | READY | Spark | D+5 | CB-002 | Daily drift report generated |
| CB-028 | Coherence | Resolve top metric mismatches | P0 | READY | Spark | D+7 | CB-027 | Drift incidents <= 1/day |
| CB-029 | Coherence | Add confidence/freshness labels to key metrics | P1 | READY | Spark | D+7 | CB-022 | Labels visible on key surfaces |
| CB-030 | Daily Loop | Run 5-section nightly self-interrogation | P0 | IN_PROGRESS | Spark | Daily | None | Daily report includes all 5 sections |
| CB-031 | Daily Loop | Top-5 daily actions + owner/ETA/proof | P0 | READY | Spark | Daily | CB-030 | Daily execution list appended |
| CB-032 | Daily Loop | 48h red-item escalation | P1 | READY | Spark | Daily | CB-031 | Escalation triggered when criteria met |
| CB-033 | Governance | Weekly SOTA delta review | P1 | READY | Spark | Weekly | CB-030 | Weekly SOTA comparison report published |

---

## Active Sprint Focus (Now)

- **Sprint A (P0, immediate):** CB-004, CB-005, CB-006, CB-007, CB-009, CB-019, CB-020, CB-023, CB-024, CB-027, CB-030
- **Success condition:** measurable improvement in memory quality, emission utility visibility, and operator actionability without new heavyweight systems.

---

## Rules of Engagement

1. Reuse existing systems first.
2. Tune before rewriting.
3. New code only where no existing pathway exists.
4. Every task must produce evidence.
5. No green status without measurable metric movement.
