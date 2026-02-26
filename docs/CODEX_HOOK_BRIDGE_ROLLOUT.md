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

## Telemetry

Shadow and observe modes both write snapshots to:

- `~/.spark/logs/codex_hook_bridge_telemetry.jsonl`

Key metrics:

- `coverage_ratio`: `mapped_events / relevant_rows`
- `pairing_ratio`: `matched_post_events / post_events`
- `post_unknown_exit`: count of post events where exit code could not be inferred
- `observe_success_ratio`: successful `observe.py` calls / total observe calls
- `observe_latency_p95_ms`: p95 hook forwarding latency

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

Outputs:

- `_observatory/codex_hooks_snapshot.json`
- `_observatory/codex_hooks.md`
- `docs/reports/<date>_codex_hooks.md`
- `<ObsidianVault>/_observatory/codex_hooks.md`

## Rollback

Immediate rollback is one switch:

- stop bridge process or revert to `--mode shadow`

No Spark core changes are required to rollback.
