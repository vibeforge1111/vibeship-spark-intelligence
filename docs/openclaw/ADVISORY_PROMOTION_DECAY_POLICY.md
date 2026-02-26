# OpenClaw Advisory Promotion And Decay Policy

Last updated: 2026-02-26
Owner: Spark Intelligence
Status: Active policy

## Purpose

Define when advisory behaviors are promoted, when they are decayed/suppressed,
and how much exploration budget is allowed before a behavior is considered stable.

This policy is designed to keep advisory quality high while preventing stale or
overfit guidance from persisting without evidence.

## Policy Goals

1. Promote only advisory patterns with measurable usefulness.
2. Decay stale patterns that stop producing outcomes.
3. Reserve explicit exploration budget so new candidates can be tested safely.
4. Keep every promotion/decay decision auditable by trace/session lineage.

## Definitions

- `candidate`: advisory pattern not yet trusted.
- `promoted`: advisory pattern eligible for normal delivery.
- `suppressed`: advisory pattern temporarily blocked pending re-test.
- `decayed`: advisory pattern demoted due to weak or stale evidence.
- `exploration budget`: bounded traffic share allocated to candidates.

## Promotion Criteria

A candidate may be promoted when all are true over the evaluation window:

1. Minimum sample size met: at least `N=20` delivered opportunities in scope.
2. Follow/acted-on rate meets target: `>= 30%` on actionable opportunities.
3. Helpfulness/effectiveness meets target: `>= 50%`.
4. No safety or policy violations observed in sampled records.
5. Quality holds across lineage slices:
   - source (`bank`, `cognitive`, `semantic`, `chip`, `mind`, `opportunity`)
   - tool family
   - session cohorts (not driven by one session outlier)

If any criterion fails, candidate remains non-promoted.

## Decay And Suppression Criteria

A promoted pattern should decay or be suppressed when one or more occur:

1. Staleness: no positive outcome links for `14` days.
2. Drift: effectiveness falls below `40%` for two consecutive windows.
3. Saturation: repeated dedupe/suppression signals indicate over-delivery.
4. Quality regression confirmed by strict attribution slices.
5. Policy breach (immediate suppression regardless of performance).

Action mapping:

- Minor drift: reduce exposure (soft decay).
- Sustained drift/staleness: demote to candidate.
- Safety/policy breach: immediate suppress and require re-qualification.

## Exploration Budget

Use a bounded exploration share for candidate traffic:

1. Default exploration budget: `10%` of eligible advisory opportunities.
2. Increase to max `15%` only during explicit tuning windows.
3. Decrease to `5%` if quality gates are unstable.
4. Exploration must be source-balanced to avoid single-source bias.

Exploration should never bypass existing guardrails, dedupe, or cooldown logic.

## Re-Test Cadence

1. Weekly strict-quality review for promoted patterns.
2. Bi-weekly stale candidate sweep.
3. Monthly policy audit:
   - promotion/decay decisions logged in changelog
   - config snapshots signed with rationale

## Minimum Audit Record Per Decision

For each promotion/decay/suppression decision, record:

1. decision type (`promote`, `decay`, `suppress`, `restore`)
2. window dates
3. sample size and key metrics
4. lineage slices summary (source/tool/session)
5. decision rationale
6. rollback/retest trigger

## Safe Defaults

1. Unknown or low-evidence behavior defaults to non-promoted.
2. Missing attribution data blocks promotion.
3. Guardrail conflicts always override promotion signals.

