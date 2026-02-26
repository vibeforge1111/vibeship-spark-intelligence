# Codex Hook Bridge Rollout

Goal: validate Codex->Spark hook parity before enabling live advisory forwarding.

## Why staged rollout

Codex has no native lifecycle hook API, so we synthesize hook events by tailing
Codex session JSONL. Shadow mode lets us verify mapping accuracy and runtime
stability before forwarding into `hooks/observe.py`.

## Commands

Single-pass historical validation:

```bash
python3 adapters/codex_hook_bridge.py --mode shadow --backfill --once
```

Continuous shadow canary:

```bash
python3 adapters/codex_hook_bridge.py --mode shadow --poll 2 --max-per-tick 200
```

Live hook forwarding (after gates pass):

```bash
python3 adapters/codex_hook_bridge.py --mode observe --poll 2 --max-per-tick 200
```

Production-safe shadow check:

```bash
python3 adapters/codex_hook_bridge.py --mode shadow --environment production --fail-on-shadow-prod
```

## Telemetry

Shadow and observe modes both write snapshots to:

- `~/.spark/logs/codex_hook_bridge_telemetry.jsonl`

Key metrics:

- `coverage_ratio`: `mapped_events / relevant_rows`
- `pairing_ratio`: `matched_post_events / post_events`
- `post_unknown_exit`: count of post events where exit code could not be inferred
- `observe_success_ratio`: successful `observe.py` calls / total observe calls
- `observe_latency_p95_ms`: p95 hook forwarding latency
- `observe_forwarding_enabled`: `true` in observe mode, `false` in shadow mode
- `workflow_event_ratio`: `(pre_events + post_events) / mapped_events`
- `tool_result_capture_rate`: `post_events / max(pre_events,1)`
- `truncated_tool_result_ratio`: `post_output_truncated / max(post_events,1)`
- `mode_shadow_ratio`: fraction of telemetry snapshots in `shadow` mode

Operational guardrails:
- singleton lock prevents multiple bridge processes (`--lock-file`, default `~/.spark/adapters/codex_hook_bridge.lock`)
- startup warning row is emitted when running long-lived shadow mode (`event=startup_warning`)
- production guard emits `warning_code=shadow_mode_in_production` when `mode=shadow` and `environment=prod|production`
- optional hard block with `--fail-on-shadow-prod` (or `SPARK_CODEX_FAIL_ON_SHADOW_PROD=1`)

Default payload capture limits (relaxed for context retention):
- input/tool args: `6000` chars (`SPARK_CODEX_HOOK_INPUT_TEXT_LIMIT`)
- tool output: `12000` chars (`SPARK_CODEX_HOOK_OUTPUT_TEXT_LIMIT`)

Summary/reference lane:
- truncated tool outputs persist full text refs under:
  - `~/.spark/workflow_refs/codex_tool_results/<sha256>.txt`
- compact workflow summaries are emitted to:
  - `~/.spark/workflow_reports/codex/workflow_<ts>_<session-hash>.json`
- summary controls:
  - `--workflow-report-dir`
  - `--workflow-summary-min-interval-s`
  - `--no-workflow-summary`

## Hypothesis Gates

Gate A (shadow stability), run across multiple sessions:

- `coverage_ratio >= 0.90`
- `pairing_ratio >= 0.90`
- `post_unknown_exit / max(post_events,1) <= 0.15`
- `json_decode_errors == 0` or clearly explained

Gate B (observe canary, one active coding session):

- `observe_success_ratio >= 0.98`
- `observe_latency_p95_ms <= 2500`
- no sustained `observe_failures` growth

Gate C (full rollout):

- Gate A and B pass for at least one workday
- then run `--mode observe` as default

## Observatory report

Generate Codex hook gate report + Obsidian page (`codex_hooks.md`):

```bash
python3 scripts/codex_hooks_observatory.py --window-minutes 60
```

Generate cross-provider workflow fidelity report (`openclaw` + `claude` + `codex`):

```bash
python3 scripts/workflow_fidelity_observatory.py --window-minutes 60
```

Stateful alerting (warning/critical across windows) uses:

- `_observatory/codex_hooks_alert_state.json`

Alert policy:
- `warning`: fidelity KPI breach in one active window
- `critical`: breach for two consecutive windows + stale telemetry

Outputs:

- `_observatory/codex_hooks_snapshot.json`
- `_observatory/codex_hooks.md`
- `docs/reports/<date>_codex_hooks.md`
- `<ObsidianVault>/_observatory/codex_hooks.md`

## Rollback

Immediate rollback is one switch:

- stop bridge process or revert to `--mode shadow`

No Spark core changes are required to rollback.
