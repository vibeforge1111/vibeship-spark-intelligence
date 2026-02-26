# OpenClaw Integration Changelog

This log tracks Spark x OpenClaw integration changes that should be easy to audit later.

## 2026-02-26

### Added

- Workflow summary lane in OpenClaw tailer:
  - compact `workflow_summary` report artifacts emitted to `<report_dir>/workflow/`
  - per-session cooldown via `workflow_summary_min_interval_s`
  - enable/disable switch via `workflow_summary_enabled`
- Large tool result reference persistence:
  - oversized tool results keep truncated inline content plus:
    - `tool_result_hash`
    - `tool_result_ref` path in `~/.spark/workflow_refs/openclaw_tool_results/`
- Recursive report ingestion:
  - OpenClaw report scanner now ingests `*.json` recursively under `report_dir`
  - processed reports are archived into sibling `.processed/` directories

### Tuneables/schema updates

- Added `openclaw_tailer.workflow_summary_enabled` (default `true`)
- Added `openclaw_tailer.workflow_summary_min_interval_s` (default `120`)
- Added tests for recursive workflow report ingest, large-output references, and summary materialization.

## 2026-02-18

### Documentation consolidation (canonicalization)

- Consolidated OpenClaw documentation surfaces:
  - canonical runtime operations doc remains `docs/OPENCLAW_OPERATIONS.md`
  - canonical tracking hub set to `docs/openclaw/README.md`
- Converted `docs/OPENCLAW_INTEGRATION.md` into a compatibility pointer to canonical docs.
- Archived full legacy integration body:
  - Internal legacy notes were moved to archived references not included in this public snapshot.
- Updated documentation index references to reduce duplicated/competing entry points.

## 2026-02-16

### Added

- Introduced canonical local path and sensitivity map:
  - `docs/OPENCLAW_PATHS_AND_DATA_BOUNDARIES.md`
- Introduced structured integration backlog:
  - `docs/openclaw/INTEGRATION_BACKLOG.md`
- Added OpenClaw config snippet/runbook reference:
  - `docs/openclaw/OPENCLAW_CONFIG_SNIPPETS.md`
- Added audit tooling + workflow docs:
  - `scripts/openclaw_integration_audit.py`
  - `docs/openclaw/OPERATIONS_WORKFLOW.md`

### Initial observed operational gaps

- OpenClaw `2026.2.15` is installed, but the active config does not explicitly set:
  - `agents.defaults.subagents.maxSpawnDepth`
  - `agents.defaults.subagents.maxChildrenPerAgent`
  - `cron.webhook` / `cron.webhookToken`
  - explicit `llm_input` / `llm_output` integration wiring
- Secrets are still present as plain values in local OpenClaw config and require hardening.

### Completed follow-up (same day)

- Hardened local OpenClaw config:
  - moved credential fields to env references,
  - set `cron.webhook` and `cron.webhookToken`,
  - set subagent policy (`maxSpawnDepth=2`, `maxChildrenPerAgent=3`).
- Added plugin-based hook telemetry capture:
  - `extensions/openclaw-spark-telemetry/`
  - captures `llm_input` + `llm_output` to redacted local spool JSONL.
- Added hook spool ingestion to Spark adapter:
  - `adapters/openclaw_tailer.py --hook-events-file ...`
- Updated integration audit detection to recognize plugin-based hook wiring.
- Added schema-transition KPI view:
  - quality GAUR now gated on `schema_version >= 2`,
  - side-by-side `gaur_all` and `feedback_schema_v2_ratio` for transition monitoring.

### Remaining next steps

1. Validate telemetry joins and strict attribution rates after sustained runtime traffic.
2. Add weekly strict-quality rollup report with lineage slices.
3. Keep each integration change as a separate commit for rollback clarity.

### Realtime verification follow-up (2026-02-16 15:00 UTC)

- Ran realtime benchmark and observed advisory check instability:
  - `docs/reports/openclaw/2026-02-16_190008_openclaw_realtime_e2e_benchmark.md`
  - Status `warn` was caused by `advisory_engine_emitted_nonzero` requiring fresh `emitted>0`, while
    the same run showed active advisory flow and high `global_dedupe_suppressed` counts.
- Hardened benchmark check semantics to reduce false warnings:
  - `scripts/openclaw_realtime_e2e_benchmark.py`
  - Check now passes when either:
    - new advisory emissions are present, or
    - emissions are dedupe-suppressed and advisory delivery is still fresh in workspace/fallback surfaces.
- Added regression tests for this logic:
  - `tests/test_openclaw_realtime_e2e_benchmark.py`

### Audit artifact

- Generated report:
  - `docs/reports/openclaw/2026-02-16_160848_openclaw_integration_audit.md`
  - `docs/reports/openclaw/2026-02-16_160848_openclaw_integration_audit.json`
  - `docs/reports/openclaw/2026-02-16_163115_openclaw_integration_audit.md`
  - `docs/reports/openclaw/2026-02-16_163115_openclaw_integration_audit.json`
