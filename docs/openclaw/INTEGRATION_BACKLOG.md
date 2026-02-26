# OpenClaw Integration Backlog

Last updated: 2026-02-18
Owner: Spark Intelligence
Status: Active

## Objective

Maintain an auditable backlog for Spark x OpenClaw integration changes, with:

- explicit gap statements,
- clear implementation tasks,
- validation criteria,
- deployment order.

## Current priorities

1. P0: Operational hardening
- [x] Move OpenClaw credentials from plain `openclaw.json` values to environment/secret-store resolution.
- [x] Configure `cron.webhook` + dedicated `cron.webhookToken` for finished-run notifications.
- [x] Enable subagent nesting policy explicitly (`maxSpawnDepth=2`, conservative `maxChildrenPerAgent`).
- [x] Wire `llm_input`/`llm_output` hook ingestion path to Spark telemetry.

2. P1: Reliability and observability
- [x] Make KPI auto-remediation resilient in all invocation contexts (module/script execution modes).
- [x] Add schema-transition dashboards for advisory feedback (`legacy` vs `schema_version=2`).
- [x] Add weekly "strict quality" rollup report with source/tool/session lineage slices.
- [x] Add redacted OpenClaw integration audit tooling (`scripts/openclaw_integration_audit.py`).
- [x] Stabilize realtime benchmark advisory signal check for dedupe-heavy windows (`scripts/openclaw_realtime_e2e_benchmark.py`).

3. P2: Governance and lifecycle
- [ ] Add formal advisory promotion/decay policy doc with exploration budget.
- [ ] Add stale advisory re-test cadence and suppression expiry policy.
- [ ] Add monthly config audit with signed changelog entry.
- [x] Consolidate OpenClaw docs into canonical runtime path + tracking hub with legacy compatibility pointers.

## Validation gates

1. Security
- [x] No raw secrets in committed files.
- [x] Ingestion artifacts contain redacted tokens and safe allowlisted fields.

2. Attribution quality
- [x] New advisory request records include `schema_version`, `trace_id`, `run_id`, `advisory_group_key`.
- [x] Strict attribution metrics are computed from trace-bound outcome joins only.

3. Runtime health
- [x] `spark-health-alert-watch` cron runs cleanly every hour.
- [x] Breach alert includes concise summary and sampled failure snapshot.
- [x] Auto-remediation only escalates after confirm delay.
- [x] Realtime benchmark can distinguish true advisory outage vs dedupe-suppressed healthy flow.

## Tracking

- Primary changelog: `docs/openclaw/INTEGRATION_CHANGELOG.md`
- Verification log: `docs/openclaw/VERIFICATION_LOG.md`
- Path/sensitivity map: `docs/OPENCLAW_PATHS_AND_DATA_BOUNDARIES.md`
- Config snippets: `docs/openclaw/OPENCLAW_CONFIG_SNIPPETS.md`
