# Context-First Contradiction Gate

This gate exists to prevent one failure mode:

we claim quality improvement from numbers while the underlying intelligence remains low-quality.

## Principle

Metrics are accepted only when item-level context evidence agrees with them.

## What this gate checks

Script: `scripts/context_first_contradiction_gate.py`

It analyzes real runtime cohorts:
- intake (`~/.spark/queue/events.jsonl`)
- memory (`~/.spark/cognitive_insights.json`)
- emission (`~/.spark/advisory_emit.jsonl`)
- suppression diagnostics (`~/.spark/advisory_engine_alpha.jsonl`)

And enforces P0 gates:
1. `unknown-gate-reason == 0`
2. `self-replay-advice == 0`
3. non-actionable emission ratio below threshold
4. telemetry/error memory ratio below threshold
5. session-weather emission ratio below threshold

## Why this matters

Without this gate, high emit/follow/trace metrics can still hide:
- vague advisories
- replayed conversational residue
- telemetry-contaminated memory
- untunable suppression behavior

## Usage

From repo root:

```bash
python scripts/context_first_contradiction_gate.py --enforce
```

Custom thresholds:

```bash
python scripts/context_first_contradiction_gate.py \
  --max-non-actionable-ratio 0.20 \
  --max-memory-telemetry-ratio 0.05 \
  --max-session-weather-ratio 0.15 \
  --enforce
```

Outputs:
- `docs/reports/*_strict_contradiction_report.md`
- `docs/reports/*_last1000_antipattern_cohorts.json`

With `--enforce`, exit code is non-zero when any P0 gate fails.
