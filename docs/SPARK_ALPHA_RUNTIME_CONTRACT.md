# Spark Alpha Runtime Contract

Last verified: 2026-02-27 (local runtime evidence, post-observatory reset)

## Purpose
Define the canonical Spark Alpha intelligence flow, required configuration, and readiness gates based on live code and command output.

## Verified Runtime Snapshot

1. Core services are running and healthy.
   - Command: `python -m spark.cli services --json`
   - Result: `mind/sparkd/pulse/bridge_worker/codex_bridge/scheduler/watchdog` all running; codex bridge telemetry fresh.
2. Integration health is green.
   - Command: `python -m lib.integration_status`
   - Result: `HEALTHY`; queue flow, advisory packet store, and codex bridge checks pass.
3. Alpha production gates are green.
   - Command: `python scripts/production_loop_report.py --json`
   - Result: `READY (19/19 passed)`.
4. Alpha readiness suite is green.
   - Command: `python scripts/alpha_start_readiness.py --strict --emit-report`
   - Result: `ready=true`, `251 passed`.
5. Codex hook quality gates are not fully green yet.
   - Command: `python scripts/codex_hooks_observatory.py --json-only`
   - Result: required failing gate is currently `observe.latency_p95_ms`.
   - Non-required warning while pending calls drain: `shadow.post_unmatched_delta`.
   - Passing now: `shadow.unknown_exit_ratio`, `observe.success_ratio`.
6. Bundled preflight is currently blocked by Codex hook gates only.
   - Command: `python scripts/alpha_preflight_bundle.py --json-only`
   - Result: `ready=false` while `production_gates.ready=true`.
7. Runtime tuneables file has schema drift to clean up.
   - Command: validate `~/.spark/tuneables.json` via `validate_tuneables(...)`.
   - Result: `2 unknown sections` remain: `section:scheduler`, `section:source_roles`.

## Canonical Alpha Flow (Runtime Truth)

1. Codex session events are tailed and mapped to hook events in [adapters/codex_hook_bridge.py](../adapters/codex_hook_bridge.py).
2. Mapped events are forwarded to [hooks/observe.py](../hooks/observe.py) in `observe` mode.
3. Hook pre/post/prompt events call alpha handlers in [lib/advisory_engine_alpha.py](../lib/advisory_engine_alpha.py):
   - `on_pre_tool`
   - `on_post_tool`
   - `on_user_prompt`
4. Hook events are also captured to queue via `quick_capture(...)` in [hooks/observe.py](../hooks/observe.py).
5. Bridge/learning loops consume queue events and update cognitive memory, distillation, and packet state.
6. Retrieval/emission for advisory responses runs through alpha runtime and advisory packet store.
7. Production quality is evaluated by [lib/production_gates.py](../lib/production_gates.py).

Note: the legacy advisory orchestrator is no longer part of the active runtime path.

## Configuration Contract (Required Paths)

1. Codex bridge mode
   - Managed startup default: `SPARK_CODEX_BRIDGE_MODE=observe` (see [lib/service_control.py](../lib/service_control.py)).
   - Manual script default remains `shadow` unless `--mode observe` is set.
2. Advisory alpha runtime config source
   - Section: `advisory_engine` in `~/.spark/tuneables.json` (resolved through config authority).
   - Consumed by [lib/advisory_engine_alpha.py](../lib/advisory_engine_alpha.py).
3. Hook budget and behavior config source
   - Section: `observe_hook` in `~/.spark/tuneables.json`.
   - Consumed by [hooks/observe.py](../hooks/observe.py).
4. Compaction/self-maintenance config source
   - Section: `sync` (`compaction_enabled`, `cognitive_actr_enabled`, packet compaction keys).
   - Consumed by [lib/context_sync.py](../lib/context_sync.py).
5. Production gate thresholds
   - Section: `production_gates`.
   - Consumed by [lib/production_gates.py](../lib/production_gates.py).

Current drift note:
- Runtime file `~/.spark/tuneables.json` still contains retired keys (for example `advisory_engine.fallback_budget_cap` and packet lookup LLM keys).
- These should be pruned to keep runtime config aligned with the active alpha surface.

## Readiness Policy

1. Core alpha ready: `production_gates.ready=true` and `alpha_start_readiness.ready=true`.
2. Codex bridge fully ready: codex observatory required gates pass (`observe.success_ratio`, `observe.latency_p95_ms`, unknown-exit ratio).
3. If core alpha is green but codex gates are red, treat as "alpha ready with codex quality gap" instead of full launch-ready.

## Operator Verification Commands

```bash
python -m spark.cli services --json
python -m lib.integration_status
python scripts/production_loop_report.py --json
python scripts/alpha_start_readiness.py --strict --emit-report
python scripts/alpha_preflight_bundle.py --json-only
python scripts/codex_hooks_observatory.py --json-only
```

## Observatory Reset + Tracking

```bash
python scripts/reset_alpha_observatory.py --yes
python scripts/alpha_intelligence_flow_status.py --json-only
```

Expected tracking artifacts:
- Local flow snapshot: `_observatory/alpha_intelligence_flow_snapshot.json`
- Local flow page: `_observatory/alpha_intelligence_flow.md`
- Vault flow page: `<ObsidianVault>/_observatory/alpha_intelligence_flow.md`
- Tracker log: `~/.spark/logs/alpha_intelligence_tracker.jsonl`
