# Advisory + Learning Benchmarks (Top 10)

Goal: ensure the advisory system emits only when it should, uses the right learned context, and closes the loop (learn -> store -> retrieve -> use -> outcome) with measurable guarantees.

This doc maps each benchmark to the *existing* Spark Intelligence harnesses/logs where possible, and calls out gaps where we still need a dedicated test.

## Benchmark Map

| # | Benchmark | What "perfect" means | Primary Harness (today) | Primary Artifacts (today) |
|---|---|---|---|---|
| 1 | Trigger Precision/Recall (When to advise) | Emit on should-emit cases; suppress on should-not-emit; minimal false emits | `benchmarks/advisory_quality_ab.py` | `benchmarks/out/*advisory_quality*_report.json|.md` |
| 2 | Advice Correctness (What to say) | Advice contains required fragments, avoids forbidden content, and is command-level actionable | `benchmarks/advisory_quality_ab.py`, `benchmarks/advisory_realism_bench.py` | `benchmarks/out/*advisory_realism*_report.json|.md` |
| 3 | Timing / Interruption Quality | Advice arrives on the correct tool boundary, respects cooldowns, and does not derail flow | Partial: cooldown + dedupe in `lib/advisory_gate.py` / engine logs; needs a direct timing bench | `~/.spark/advisory_engine.jsonl` + (gap: a timing-only benchmark) |
| 4 | Learning Capture Quality (Write) | New learnings are distilled (not raw telemetry), deduped, non-contradictory, and scoped | `tests/test_cognitive_capture.py`, `tests/test_cognitive_validation_hygiene.py` | `~/.spark/cognitive_insights.json`, `~/.spark/meta_ralph/*` |
| 5 | Learning Retrieval Accuracy (Read) | Relevant learnings are retrieved at high recall with low irrelevant pull-in | `benchmarks/memory_retrieval_ab.py` | `benchmarks/out/*memory_retrieval*_report.json|.md` |
| 6 | Contextual Gating / Scope Control | Learnings apply only in-scope; similar-but-wrong cases do not trigger | `tests/test_advisory_intent_taxonomy.py`, `tests/test_advisory_gate_config.py`, realism suppress cases | realism reports + `~/.spark/advisory_engine.jsonl` |
| 7 | Conflict & Priority Resolution | When sources conflict, policy/priority rules choose deterministically and consistently | Partial: retrieval routing + fusion tests; needs explicit conflict fixtures | `tests/test_advisory_memory_fusion.py`, `tests/test_advisor_retrieval_routing.py` |
| 8 | Recency / Expiry / Versioning | Newer learnings supersede old; deprecated learnings stop affecting behavior | Partial: dedupe/cooldown exists; needs explicit expiry/version fixtures | (gap) |
| 9 | Robustness (Ambiguity + Injection) | No hallucinated learnings; rejects memory/tool prompt injection; safe-by-default | `tests/test_safety_guardrails.py`, `tests/test_strict_attribution_integration.py` | test outputs + runtime logs |
| 10 | End-to-End Outcomes (Online) | Improves completion rate/time/error recovery without annoyance | `tests/test_learning_utilization.py`, `tests/test_advisor_effectiveness.py`, dashboard | `~/.spark/advisor/effectiveness.json`, dashboard endpoints |

## Concrete Pass/Fail Criteria (Recommended Defaults)

These thresholds are intentionally aligned with the existing realism contract gates and utilization grading.

1. Trigger correctness:
   - `benchmarks/advisory_quality_ab.py`: `emit_accuracy >= 0.85`
   - `benchmarks/advisory_realism_bench.py`: `harmful_emit_rate <= 0.10`, `critical_miss_rate <= 0.10`

2. Actionability + binding:
   - `trace_bound_rate >= 0.85`
   - `actionability_rate >= 0.60` (raise once advisory is stable)

3. Source alignment (memory used at the right times):
   - `source_alignment_rate >= 0.55` (per `REALISM_GATES` in `benchmarks/advisory_realism_bench.py`)
   - `memory_utilization_rate` should be trending up without increasing harmful/unsolicited emits

4. Utilization loop health:
   - `python tests/test_learning_utilization.py`: grade `>= C` for dev; `>= B` for production hardening

## Real-Time "What's Happening Right Now" Runbook

These commands are meant to be run on the *active* environment, not a synthetic-only setup.

1. Service + queue health:
```bash
python scripts/status_local.py
python tests/test_pipeline_health.py quick
```

2. Learning utilization snapshot:
```bash
python tests/test_learning_utilization.py quick
```

3. Advisory quality (fast, focused):
```bash
python benchmarks/advisory_quality_ab.py ^
  --cases benchmarks/data/advisory_quality_eval_seed.json ^
  --profiles baseline,balanced,strict ^
  --repeats 1 ^
  --force-live ^
  --out-prefix advisory_quality_ab_live_now
```

4. Advisory realism (contracted, production-grade):
```bash
python scripts/run_advisory_realism_contract.py
```

5. Human-readable self review (last N hours):
```bash
python scripts/advisory_self_review.py --window-hours 24
```

### Priority Live Checks (Noise + Trace Binding)

These are the first two fixes we started with because they unblock reliable evaluation:

1. Benchmark (2): Outcome binding is trace-consistent (no fresh mismatches):
```bash
python scripts/advisory_self_review.py --window-hours 0.25 --json
```
- Expect: `outcomes.trace_mismatch_count` is trending to `0` for *new* records.
- Tip: use a shorter window like `--window-hours 0.1` (6 minutes) to isolate "just now" behavior.
- Artifact: `~/.spark/meta_ralph/outcome_tracking.json`

2. Benchmark (1): Global anti-spam dedupe suppresses repeat advice across session churn:
```bash
python scripts/advisory_self_review.py --window-hours 0.25 --json
```
- Expect: `recent_advice.repeated_texts` share stops climbing for the same `advice_id` in short windows.
- Expect: engine events include `global_dedupe_suppressed` when repeats are blocked.
- Artifacts:
  - `~/.spark/advisory_engine.jsonl`
  - `~/.spark/advisory_global_dedupe.jsonl`
- Tuneables (canonical: `advisory_engine` section in `~/.spark/tuneables.json`):
  - `global_dedupe_enabled` (env override: `SPARK_ADVISORY_GLOBAL_DEDUPE=0|1`)
  - `global_dedupe_by_text` (env override: `SPARK_ADVISORY_GLOBAL_DEDUPE_BY_TEXT=0|1`, default true)
  - `global_dedupe_cooldown_s` (env override: `SPARK_ADVISORY_GLOBAL_DEDUPE_COOLDOWN_S=600`, default 10 min)

### Advice ID Stability (Prevents Churn + Fragmented Outcomes)

The advisory system relies on stable `advice_id` values to avoid spam and to correctly accumulate outcomes over time.

- Current rule: for durable sources (e.g. cognitive, mind, bank, chips, eidos), `advice_id` is derived from `source:insight_key` when available.
- Semantic/trigger retrieval routes are canonicalized back to the underlying store (`cognitive`) for ID purposes.

Quick audit (how many distinct advice IDs exist for one stable insight key in recent deliveries):
```bash
python -c "import os,json,pathlib; from collections import Counter; p=pathlib.Path(os.path.expanduser('~/.spark/advisor/recent_advice.jsonl')); key='reasoning:always_read_a_file_before_edit_to_verify'; rows=[]; \nfor ln in p.read_text('utf-8', errors='ignore').splitlines()[-5000:]:\n r=json.loads(ln); iks=r.get('insight_keys') or []; aids=r.get('advice_ids') or []; \n for i,ik in enumerate(iks):\n  if ik==key: rows.append(aids[i] if i < len(aids) else None);\nctr=Counter([x for x in rows if x]); print('matches',len(rows),'unique_advice_ids',len(ctr)); print('top',ctr.most_common(5))"
```

## Tomorrow Checklist (2026-02-16)

State at end of day:
- Outcome trace binding: new-window mismatches should be `0` when running `scripts/advisory_self_review.py --window-hours 0.1 --json`.
- Advice ID stability: new deliveries for `reasoning:always_read_a_file_before_edit_to_verify` now use stable `advice_id` `cognitive:reasoning:always_read_a_file_before_edit_to_verify`.
- Global dedupe: engine emits `global_dedupe_suppressed` when repeats are blocked; log at `~/.spark/advisory_global_dedupe.jsonl`.

Remaining work for tomorrow:
1. Confirm stable IDs in the full engine loop (packet + live paths), not just direct `advise_on_tool`:
```bash
python scripts/advisory_self_review.py --window-hours 0.1 --json
```
2. Spot-check that packets created before advice-id stabilization do not reintroduce churn:
   - Trigger packet path by running a few normal tool calls.
   - Inspect `~/.spark/advisor/recent_advice.jsonl` for repeated `insight_key` with changing `advice_id`.
3. Optional: add a small metric in `scripts/advisory_self_review.py` for “advice_id churn per insight_key” over window.

Zoomed-out priorities for tomorrow:
1. Validate the full loop stays healthy online (not just unit tests):
   - `recent_advice.trace_coverage_pct` near 100% for tool-driven emissions
   - `outcomes.trace_mismatch_count` stays 0 in short windows
   - `engine.fallback_share_pct` stays low (no accidental gate regressions)
2. Ensure advice spam is actually reduced in practice:
   - confirm `global_dedupe_suppressed` appears when repeats are attempted
   - confirm `recent_advice.repeated_texts` share trends down over a longer window (ex: 1-6 hours)
3. Check outcome application is flowing back to cognitive reliability:
   - verify `~/.spark/meta_ralph/outcome_tracking.json` records include `insight_key` and `source=cognitive` for cognitive items
   - verify `~/.spark/cognitive_insights.json` reliability/validations are not fragmenting due to old random advice IDs
4. Packet store health:
   - confirm packets no longer emit legacy/random advice IDs when `insight_key` exists (migration in `_packet_to_advice`)
   - optionally invalidate/delete a few stale packets if they keep resurfacing noisy content

Morning run sequence (fast):
```bash
python scripts/status_local.py
python scripts/advisory_self_review.py --window-hours 0.1 --json
python -m pytest -q tests/test_advice_id_stability.py
```

If time tomorrow (evaluation, not just “seems fixed”):
1. Run contracted realism:
```bash
python scripts/run_advisory_realism_contract.py
```
2. Run a quick advisory quality sweep:
```bash
python benchmarks/advisory_quality_ab.py --profiles baseline,balanced,strict --repeats 1
```
3. Add a churn metric to self-review output:
   - “top insight_keys by unique advice_id count in window”
   - “top insight_keys by global dedupe suppressions”

Where to continue from:
- Benchmarks + runbook: `docs/ADVISORY_AND_LEARNING_BENCHMARKS.md`
- Stability regression test: `tests/test_advice_id_stability.py`

Notes:
- `recent_advice.trace_coverage_pct` can be lower if you call the advisor directly outside the observed tool loop (no `trace_id` available).

## Observability Pointers

- Advisory engine event log: `~/.spark/advisory_engine.jsonl`
- Retrieval routing telemetry: `~/.spark/advisor/retrieval_router.jsonl`
- Recent advice feed: `~/.spark/advisor/recent_advice.jsonl`
- Advisor effectiveness: `~/.spark/advisor/effectiveness.json`
- Meta-Ralph outcome tracking: `~/.spark/meta_ralph/outcome_tracking.json`

## Known Gaps (Where We Still Need Dedicated Benches)

1. Timing / interruption: a benchmark that explicitly scores *insertion turn correctness* (early/late windows) rather than only "emit vs suppress".
2. Conflict resolution: fixtures that force contradictory learnings across sources (cognitive vs mind vs outcomes) and assert deterministic priority behavior.
3. Recency/expiry/versioning: fixtures that ensure "new supersedes old" and "deprecated stops applying" across both retrieval and advisory synthesis.

