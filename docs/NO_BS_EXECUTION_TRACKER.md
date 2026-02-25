# Spark Intelligence — No-BS Execution Tracker

**Source report:** `docs/NO_BS_GAP_REPORT_2026-02-25.md`  
**Mode:** execution-first, evidence-required  
**Update cadence:** daily (23:00 Asia/Dubai)

---

## 1) North-Star Outcome

Move Spark from **LIMITED READY** to **READY for controlled scale** by closing attribution, queue/sync coherence, onboarding reliability, and LLM lane governance.

---

## 2) Hard Gate Targets (must stay green)

| Metric | Current (baseline) | Target | Owner | Status |
|---|---:|---:|---|---|
| Noise burden | 0.758 | <= 0.65 | Advisory/Quality | 🔴 |
| Strict trace coverage | 10% | >= 50% | Core Pipeline | 🔴 |
| Strict acted_on rate | 3.9% | >= 20% | Advisory/Outcome | 🔴 |
| Advisory packet freshness | 0.0 | >= 0.35 | Advisory Store | 🔴 |
| Advisory packet readiness | 0.0 | >= 0.40 | Advisory Store | 🔴 |
| Mind offline queue depth | 14,469 | <= 2,000 | Mind Bridge | 🔴 |
| Watchdog uptime | false (inactive) | >= 99% | Platform/Ops | 🔴 |
| Onboarding 1st-try success | TBD | >= 85% | Onboarding | ⚪ |
| Time-to-first-useful-advice | TBD | <= 20 min | Onboarding + Advisory | ⚪ |

Legend: 🔴 blocked / 🟡 in progress / 🟢 on target / ⚪ not instrumented yet

---

## 3) 14-Day Action Plan (owner, ETA, status)

## P0 (Days 1-3)

| ID | Workstream | Deliverable | Owner | ETA | Status | Proof of Done |
|---|---|---|---|---|---|---|
| P0-1 | Metric coherence | Unified queue truth panel (event/pending/offline) + schema contract | Core Pipeline | D+3 | 🔴 | One canonical metric source used by `status`, KPI scorecard, and Observatory |
| P0-2 | Runtime resilience | Watchdog restored + alert if down >2 cycles | Platform/Ops | D+2 | 🔴 | `watchdog.running=true` + alert test log |
| P0-3 | Attribution | Trace-linkage patch v1 (strict coverage lift) | Core Pipeline | D+3 | 🔴 | strict trace coverage >=35% sustained for 24h |

## P1 (Days 4-7)

| ID | Workstream | Deliverable | Owner | ETA | Status | Proof of Done |
|---|---|---|---|---|---|---|
| P1-1 | Advisory freshness | Packet TTL/invalidation/key stability fix | Advisory Store | D+7 | 🔴 | readiness >=0.25 and freshness >=0.20 in 24h gate |
| P1-2 | Noise reduction | Suppression/dedupe tuning sprint | Advisory/Quality | D+7 | 🔴 | noise burden <=0.68 sustained 24h |
| P1-3 | Onboarding reliability | `spark onboard verify --strict` scorecard | Onboarding | D+7 | 🔴 | verifier returns pass/fail + score + remediation hints |

## P2 (Days 8-14)

| ID | Workstream | Deliverable | Owner | ETA | Status | Proof of Done |
|---|---|---|---|---|---|---|
| P2-1 | LLM lane UX | Onboarding LLM lane selector (advisory/eidos/meta/opportunity/packet) | Onboarding + LLM | D+12 | 🔴 | user can configure per-lane provider in one flow |
| P2-2 | LLM governance | Per-lane budget + privacy class controls | LLM Platform | D+13 | 🔴 | budget caps enforced + privacy policy report |
| P2-3 | Model quality ops | Provider×lane outcome leaderboard | Observability | D+14 | 🔴 | dashboard/report ranking by quality/cost/latency |

---

## 4) Risk Register (active)

| Risk | Impact | Probability | Mitigation | Owner | Status |
|---|---|---|---|---|---|
| Metric mismatch persists across surfaces | Wrong prioritization by leadership | High | Enforce single metric schema + contract tests | Core Pipeline | 🔴 |
| Queue debt keeps rising despite fixes | Stale advisory context | High | Drain policy + backpressure + sync retries | Mind Bridge | 🔴 |
| Trace coverage improves but acted_on remains low | False confidence in attribution | Medium | tighten outcome-link windows + link quality checks | Advisory/Outcome | 🔴 |
| Onboarding changes increase complexity | Lower conversion | Medium | progressive mode rollout + telemetry A/B | Onboarding | 🔴 |
| Multi-provider LLM causes cost drift | Budget overrun | Medium | per-lane caps + kill-switch + weekly audit | LLM Platform | 🔴 |

---

## 5) Daily Operating Cadence

1. Run hard-gate checks.
2. Update this tracker (status + blockers + evidence links).
3. Post no-BS summary (what moved / what did not).
4. Escalate any item red for >48h without measurable progress.

---

## 6) Daily Update Template

```md
## Daily Update — YYYY-MM-DD

### Gate Snapshot
- Noise burden:
- Strict trace coverage:
- Strict acted_on rate:
- Packet freshness/readiness:
- Offline queue depth:
- Watchdog:

### What moved today
- 

### What is still blocked
- 

### Regressions detected
- 

### Next 24h actions
1.
2.
3.
```

---

## 7) Escalation Rules

- Any hard gate red for 3 consecutive days → mandatory escalation + owner reassignment.
- Any metric disagreement across dashboards for >24h → freeze release claims until reconciled.
- Any onboarding rollback in first 10 mins >15% → rollback recent onboarding change.

---

## 8) Release Decision Rule

Release posture can move to **READY** only if all are true for 7 consecutive days:
- noise burden <= 0.65
- strict trace coverage >= 0.50
- strict acted_on rate >= 0.20
- packet freshness >= 0.35 and readiness >= 0.40
- offline queue <= 2,000
- watchdog uptime >= 99%
- onboarding first-try success >= 85%
