# Spark Alpha Phased Stability Plan (Post-Wipe)

Updated: 2026-02-27
Branch: `feat/spark-alpha`

## 0) Baseline context
- Runtime state was wiped, so outcome-heavy claims (promotion quality, long-window effectiveness, WAL growth, telemetry growth) need fresh data.
- We still have enough static code evidence to fix clear wiring defects immediately.

## 1) Issue triage from Claude feedback

Legend:
- `CONFIRMED`: verified in current code.
- `PARTIAL`: claim is directionally true but overstated or mixed.
- `NEEDS_DATA`: cannot be judged yet after wipe without runtime accumulation.

| ID | Claim | Status | Action phase |
|---|---|---|---|
| 1 | `sparkd.py` / `spark/cli.py` import deleted advisory module | CONFIRMED | Phase 1 (fixed now) |
| 2 | LLM EIDOS writes JSONL while advisor primarily reads EIDOS SQLite | CONFIRMED | Phase 1 (risk mitigated now), Phase 2 finalize |
| 3 | Bridge LLM advisory bypasses alpha advisory engine | CONFIRMED | Phase 1 (fixed now) |
| 4 | Cognitive learner retrieval function is orphaned | PARTIAL | Phase 3 design decision |
| 5 | Unified noise classifier stuck in shadow mode | CONFIRMED | Phase 2 decision (enforce vs remove) |
| 6 | Promoter reads JSON not SQLite canonical | PARTIAL | Phase 2 runtime verification |
| 7 | Opportunity scanner EIDOS observation path is dead-ended | CONFIRMED (tied to #2) | Phase 1 mitigated |
| 8 | Legacy advisory canary path still active | PARTIAL | Phase 3 removal gate |
| 9 | `cognitive_signals.py` duplicates pipeline | PARTIAL | Phase 2 evidence collection |
| 10 | Legacy `update_spark_context()` duplicates alpha sync | CONFIRMED | Phase 2 controlled removal |
| 11 | Auto-tuner dampening cognitive may be counter-productive | NEEDS_DATA | Phase 2 |
| 12 | Promotions not happening correctly | NEEDS_DATA | Phase 2 |
| 13 | Semantic retrieval operates in rescue/fallback most of the time | CONFIRMED | Phase 1 (fixed now) |
| 14 | `by_source` effectiveness has no time decay | CONFIRMED | Phase 2 |
| 15 | SQLite timeout missing for memory/EIDOS stores | CONFIRMED | Phase 2 |
| 16 | Shadow telemetry + advisory state growth lack hygiene | CONFIRMED | Phase 1 partial (session cleanup wired), Phase 2 complete |
| 17 | WAL files can grow disproportionately | NEEDS_DATA | Phase 2 |
| 18 | Chips/Mind work still runs when effectively disabled | PARTIAL | Phase 3 |
| 19 | Large env-var override surface lacks conflict validation | CONFIRMED | Phase 3 |
| 20 | Deprecated `curiosity_engine.py` still present | CONFIRMED | Phase 3 |
| 21 | Raw user questions can be promoted as learnings | CONFIRMED | Phase 1 (fixed now), Phase 2 attribution hardening |

## 2) Phase 1: Fix-now defects (high confidence, high impact)

Status: implemented on this branch.

1. Advisory import crash fix
- `sparkd.py` now imports hooks from `lib.advisory_engine_alpha`.
- `spark/cli.py` now reads runtime state from `get_alpha_status()` (legacy fallback kept fail-safe only).

2. Remove advisory bypass path from default runtime
- Bridge-side LLM advisory sidecar is now default-off (`BRIDGE_LLM_ADVISORY_SIDECAR_ENABLED=false`).
- Alpha advisory engine remains the single authoritative advisory output path.

3. Disable orphan EIDOS sidecar path by default
- Bridge LLM EIDOS sidecar is default-off (`BRIDGE_LLM_EIDOS_SIDECAR_ENABLED=false`).
- Prevents generating distillations that bypass canonical EIDOS retrieval path.

4. Retrieval degradation guardrail for TF-IDF mode
- Semantic retriever now auto-recalibrates thresholds when backend is TF-IDF and config is default-loaded.
- Prevents perpetual rescue-fallback behavior under high neural-tuned thresholds.

5. Question/noise capture guardrails (anti-pollution)
- Added user-question filtering in `memory_capture` before scoring and storage.
- Added question guard in `meta_alpha_scorer`.
- Expanded unified noise classifier for short question fragments.
- Promoter legacy filter now rejects question-like conversational items.

6. Advisory state hygiene
- Wired `cleanup_expired_states()` into bridge runtime hygiene step.

## 3) Phase 2: data-gathered stabilization (next 24-72h)

Do only after accumulating fresh post-wipe runtime data.

1. Decide and execute noise classifier policy
- Option A: enforce unified classifier.
- Option B: remove shadow lane and keep legacy.
- Gate: disagreement sample size >= 200 with precision checks.

2. Resolve EIDOS dual-path permanently
- Either route all LLM distillation output into canonical EIDOS store API, or delete LLM sidecar code.
- Gate: retrieval hit quality unchanged or improved in replay arena.

3. Time-decay source effectiveness
- Add decay semantics to `effectiveness.by_source`.
- Gate: no old-run poisoning in source boosts.

4. SQLite reliability hardening
- Add consistent `timeout` handling to memory spine + EIDOS store connections.
- Gate: no `database is locked` events in stress run.

5. Promotion precision audit
- Measure promoted-item precision over fresh data.
- Gate: >= 80% promotions are actionable distilled insights (not transcript fragments).

## 4) Phase 3: legacy reduction and simplification

1. Remove duplicated context update path (`update_spark_context`) after proving parity with `sync_context`.
2. Remove stale/deprecated modules (including `curiosity_engine.py`) only after green replay + smoke.
3. Reduce env override risk by validating conflicting env combinations at startup.
4. Remove canary/legacy advisory route after replay streak gate.

## 5) Required verification stack per phase

### Unit + integration
```bash
pytest -q tests/test_sparkd_openclaw_runtime_bridge.py tests/test_cli_advisory.py tests/test_bridge_cycle_safety.py tests/test_memory_capture_safety.py tests/test_noise_classifier.py tests/test_promoter_noise_classifier.py tests/test_semantic_retriever.py tests/test_meta_alpha_scorer_guardrails.py
```

### Runtime smoke
```bash
python -m scripts.production_loop_report
python scripts/alpha_intelligence_flow_status.py
python scripts/spark_alpha_replay_arena.py --smoke
python scripts/advisory_controlled_delta.py --smoke
```

### Daily observability
```bash
python scripts/workflow_fidelity_observatory.py
```

## 6) Alpha readiness gate (post-wipe)

Release to alpha only when all are true:
- No advisory import/runtime crashes.
- No default bridge advisory bypass path.
- No default orphan EIDOS distillation path.
- Replay arena shows alpha wins on consecutive runs.
- Production loop report reaches READY with strict sample floors met.
- Promotion precision and retrieval precision pass fresh post-wipe thresholds.
