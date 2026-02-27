# Spark Alpha 2-Hour Launch Readiness

Date: 2026-02-27
Branch: `feat/spark-alpha`

## Go/No-Go Criteria
1. `python scripts/alpha_start_readiness.py --emit-report --strict` returns `ready=true`.
2. Advisory spine parity gate passes with streak `>=3`.
3. Replay evidence has 3 consecutive runs (`episodes=20`) with:
   - `winner=alpha`
   - `promotion_gate_pass=true`
4. Controlled-delta smoke completes successfully.
5. Rollback control is explicit and tested.

## Current Status
Verdict: `GO` (criteria met)

### 1) Strict readiness
- Command: `python scripts/alpha_start_readiness.py --emit-report --strict`
- Result: `ready=true`
- Artifact JSON: `benchmarks/out/alpha_start/alpha_start_readiness_20260227_175351.json`
- Artifact MD: `benchmarks/out/alpha_start/alpha_start_readiness_20260227_175351.md`

### 2) Advisory spine parity streak
- Command: `python scripts/advisory_spine_parity_gate.py --required-streak 3`
- Result:
  - `pass=true`
  - `payload_parity_ratio=1.0`
  - `streak=3`
  - `ready_for_index_meta_retirement=true`
- Ledger: `%USERPROFILE%\.spark\advisory_spine_parity_ledger.jsonl`

### 3) Replay evidence (3 runs, 20 episodes)
- Command:
  - `python scripts/run_alpha_replay_evidence.py --seeds 42,77,99 --episodes 20 --out-dir benchmarks/out/replay_arena`
- Result (from latest report):
  - `runs=3`
  - `alpha_wins=3`
  - `promotion_passes=3`
  - `alpha_win_rate=1.0`
  - `promotion_pass_rate=1.0`
- Artifact JSON: `benchmarks/out/replay_arena/spark_alpha_replay_evidence_20260227_175952.json`
- Artifact MD: `benchmarks/out/replay_arena/spark_alpha_replay_evidence_20260227_175952.md`

### 4) Controlled delta
- Command:
  - `python scripts/advisory_controlled_delta.py --rounds 2 --label alpha_launch_gate --out benchmarks/out/advisory_delta_alpha_launch_gate.json`
- Result:
  - `rounds=2`
  - `emitted_returns=2`
  - `engine.trace_coverage_pct=100.0`
  - `config.advisory_route.mode=alpha`
- Artifact JSON: `benchmarks/out/advisory_delta_alpha_launch_gate.json`

### 5) Rollback control
- Emergency advisory-off switch:
  - `set SPARK_ADVISORY_ALPHA_ENABLED=0`
- Restore advisory-on:
  - `set SPARK_ADVISORY_ALPHA_ENABLED=1`
- Validation:
  - `python -c "import os; from lib.doctor import run_doctor; os.environ['SPARK_ADVISORY_ALPHA_ENABLED']='0'; print([c.message for c in run_doctor().checks if c.id=='advisory_engine'][0])"`
  - `python -c "import os; from lib.doctor import run_doctor; os.environ['SPARK_ADVISORY_ALPHA_ENABLED']='1'; print([c.message for c in run_doctor().checks if c.id=='advisory_engine'][0])"`

## Not Included In 2-Hour Launch Cut
1. Full config collapse to ~70 keys.
2. Full distillation pipeline collapse.
3. Full utility dedup sweep.
4. VibeForge code-evolve lane (kept deferred by design).
