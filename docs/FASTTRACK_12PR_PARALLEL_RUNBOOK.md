# FastTrack 12-PR Parallel Runbook (3 Agents)

**Date**: 2026-02-26  
**Mode**: Execution today  
**Goal**: Deliver the 12 PR sequence with 3 parallel agents per round, merge after each round, and continue.

---

## 1) Execution Rules

1. Run exactly 3 PRs in parallel per round.
2. Each PR is isolated in its own worktree.
3. No direct commit to `main`.
4. Every PR must include:
   - code changes
   - verification output summary
   - rollback note
5. Round merges happen only after review gate passes.
6. Follow repo branch-prefix policy: use only `feat/`, `fix/`, `docs/`.

## 1.1) Commit Volume and Quality Policy

This run requires high commit velocity without spaghetti. Use micro-commits with strict structure.

Commit cadence per PR:
1. Target `6-12` commits per PR.
2. Maximum `1 concern` per commit.
3. Prefer `<= 6` files touched per commit.
4. Prefer `<= 250` net lines per commit unless explicitly justified.

Required commit sequence (default):
1. `scaffold`: interfaces/types/flags (no behavior switch).
2. `core`: behavior change.
3. `tests`: targeted tests for changed behavior.
4. `telemetry`: logs/metrics parity evidence.
5. `docs`: runbook/contract updates.
6. `cleanup`: dead code removal or naming cleanup.

Commit message format:
1. `feat(<scope>): <atomic change>`
2. `fix(<scope>): <atomic fix>`
3. `docs(<scope>): <atomic docs update>`

Forbidden:
1. Mixed feature + refactor + docs in one commit.
2. Drive-by unrelated edits in active PR.
3. New abstraction without immediate caller and test.

## 1.2) Anti-Spaghetti Architecture Invariants

These are merge-blocking invariants for all 12 PRs.

Layer boundaries:
1. `hooks/*` and capture path must not depend on advisory internals.
2. Advisory runtime must access persistence via store/facade APIs, not raw `~/.spark` file reads.
3. `scripts/*` are orchestration/reporting only and must not become runtime dependencies of `lib/*`.
4. One canonical implementation per shared utility function. No copy-paste helpers.

State boundaries:
1. New state writes must be explicit and observable.
2. No hidden global mutable state additions without justification.
3. Feature flags must default safe and be reversible.

Complexity boundaries:
1. No new subsystem unless one old subsystem is removed or deprecated in same PR set.
2. No new config section without measurable gate and rollback hook.
3. Keep interfaces small and explicit; avoid premature abstraction layers.

Quick boundary checks before merge:
1. `rg -n "Path.home\\(\\) / \".spark\"" lib -g "*.py"`
2. `rg -n "^from lib\\.|^import lib\\." hooks lib -g "*.py"`
3. `rg -n "_tail_jsonl\\(|_append_jsonl_capped\\(|_safe_float\\(|_parse_bool\\(" lib -g "*.py"`

---

## 2) Team Roles

1. `Agent-A`: owns track A PR in each round.
2. `Agent-B`: owns track B PR in each round.
3. `Agent-C`: owns track C PR in each round.
4. `Integrator`: reviews, merges, tags checkpoint, starts next round.

---

## 3) Workspace Setup (PowerShell)

Run once from repo root:

```powershell
git fetch origin
git checkout -B fasttrack/integration origin/main
git worktree add ..\spark-agent-a fasttrack/integration
git worktree add ..\spark-agent-b fasttrack/integration
git worktree add ..\spark-agent-c fasttrack/integration
```

After each round merge, sync all worktrees:

```powershell
git checkout fasttrack/integration
git pull --ff-only
git -C ..\spark-agent-a checkout fasttrack/integration
git -C ..\spark-agent-a pull --ff-only
git -C ..\spark-agent-b checkout fasttrack/integration
git -C ..\spark-agent-b pull --ff-only
git -C ..\spark-agent-c checkout fasttrack/integration
git -C ..\spark-agent-c pull --ff-only
```

---

## 4) Round Plan (3 PRs At A Time)

## Round 1 (Foundations, user-visible quality starts)

1. `PR-01` Metric Contract Lock
2. `PR-03` Capture Noise Hygiene V1
3. `PR-05` Repeat/Dedupe Rework (flagged)

## Round 2 (Attribution + context + trial gate)

1. `PR-02` Strict Trace Binding Hardening
2. `PR-04` Context Floor + Write Enrichment V1
3. `PR-06` Canary + Ship Gate Automation

## Round 3 (Core replacement path)

1. `PR-07` SQLite Backbone (Dual-Write)
2. `PR-09` Unified Noise Classifier Integration
3. `PR-10` Advisory Facade + Route Flags

## Round 4 (Validation + loop + cleanup)

1. `PR-08` SQLite Read Shadow + Parity Report
2. `PR-11` Nightly One-Delta Self-Improve Loop
3. `PR-12` Wave-1 Deletions + Config Packdown

## 4.1) Branch Creation Commands Per Round

Round 1:

```powershell
git -C ..\spark-agent-a checkout -b feat/fasttrack-pr-01-metric-contract
git -C ..\spark-agent-b checkout -b feat/fasttrack-pr-03-capture-noise-hygiene
git -C ..\spark-agent-c checkout -b feat/fasttrack-pr-05-dedupe-rework
```

Round 2:

```powershell
git -C ..\spark-agent-a checkout -b feat/fasttrack-pr-02-strict-trace-binding
git -C ..\spark-agent-b checkout -b feat/fasttrack-pr-04-context-floor-enrichment
git -C ..\spark-agent-c checkout -b feat/fasttrack-pr-06-ship-gate-automation
```

Round 3:

```powershell
git -C ..\spark-agent-a checkout -b feat/fasttrack-pr-07-sqlite-dual-write
git -C ..\spark-agent-b checkout -b feat/fasttrack-pr-09-unified-noise-classifier
git -C ..\spark-agent-c checkout -b feat/fasttrack-pr-10-advisory-facade
```

Round 4:

```powershell
git -C ..\spark-agent-a checkout -b feat/fasttrack-pr-08-sqlite-read-shadow
git -C ..\spark-agent-b checkout -b feat/fasttrack-pr-11-nightly-one-delta
git -C ..\spark-agent-c checkout -b feat/fasttrack-pr-12-wave1-deletions
```

---

## 5) Per-PR Cards (Exact Implementation Scope)

## PR-01 Metric Contract Lock

- Branch: `feat/fasttrack-pr-01-metric-contract`
- Target files:
  - `docs/observability/HEALTH_CONTRACT.md`
  - `scripts/memory_quality_observatory.py`
  - `lib/production_gates.py`
  - `docs/reports/*` generator paths touched by metric definitions
- Implement:
  1. Canonical formula/source map for each KPI.
  2. Emit explicit metric version in outputs.
  3. Add drift-check comparison against canonical map.
- Verify:
  - `python scripts/memory_quality_observatory.py`
  - `python scripts/production_loop_report.py`
  - `python scripts/generate_observatory.py --force --verbose`
- Merge gate: no formula conflicts and drift report generated.
- Rollback: revert metric-map changes only.

## PR-02 Strict Trace Binding Hardening

- Branch: `feat/fasttrack-pr-02-strict-trace-binding`
- Target files:
  - `lib/advisory_engine.py`
  - `lib/action_matcher.py`
  - `lib/advice_feedback.py`
  - `scripts/advisory_day_trial.py`
- Implement:
  1. Ensure advisory emission always carries trace ID.
  2. Ensure matched outcomes persist same trace lineage.
  3. Tighten strict attribution window behavior.
- Verify:
  - `python -m pytest tests/test_strict_attribution_integration.py -q`
  - `python scripts/production_loop_report.py`
- Merge gate: strict trace coverage trend improves in report.
- Rollback: disable strict binding enforcement toggle.

## PR-03 Capture Noise Hygiene V1

- Branch: `feat/fasttrack-pr-03-capture-noise-hygiene`
- Target files:
  - `hooks/observe.py`
  - `lib/memory_capture.py`
  - `lib/meta_ralph.py`
- Implement:
  1. Remove top repeated low-signal capture patterns.
  2. Add targeted noise suppression for scaffolding artifacts.
  3. Keep telemetry reasons for all suppressions.
- Verify:
  - `python scripts/memory_quality_observatory.py`
  - `python scripts/carmack_kpi_scorecard.py --window-hours 24 --alert-json`
- Merge gate: no new error spikes; capture noise moves down.
- Rollback: revert new pattern suppressions.

## PR-04 Context Floor + Write Enrichment V1

- Branch: `feat/fasttrack-pr-04-context-floor-enrichment`
- Target files:
  - `lib/memory_capture.py`
  - `lib/cognitive_learner.py`
  - `lib/advisory_memory_fusion.py`
- Implement:
  1. Enforce minimum context payload floor.
  2. Add write-time context enrichment for stored memory.
  3. Keep original payload available for audit/debug.
- Verify:
  - `python scripts/memory_quality_observatory.py`
  - `python -m pytest tests/test_memory_capture_safety.py -q`
- Merge gate: `context.p50` trend up with no guardrail regression.
- Rollback: turn off enrichment and context floor flags.

## PR-05 Repeat/Dedupe Rework (Flagged)

- Branch: `feat/fasttrack-pr-05-dedupe-rework`
- Target files:
  - `lib/advisory_engine.py`
  - `lib/advisory_gate.py`
  - `lib/advisory_packet_store.py`
- Implement:
  1. Replace broad global dedupe with contextual/category-aware windowing.
  2. Add repeat suppression for identical low-value advisories.
  3. Preserve stricter handling for high-authority advisories.
- Verify:
  - `python scripts/advisory_day_trial.py snapshot --trial-id fasttrack_w1 --run-canary --timeout-s 1800`
- Merge gate: repeat concentration down; no unhelpful spike.
- Rollback: revert dedupe policy and cooldowns.

## PR-06 Canary + Ship Gate Automation

- Branch: `feat/fasttrack-pr-06-ship-gate-automation`
- Target files:
  - `scripts/advisory_day_trial.py`
  - `scripts/run_advisory_retrieval_canary.py`
  - `docs/reports/canaries/*` templates
- Implement:
  1. Standardize pass/fail schema for canary decisions.
  2. Add explicit stop conditions and auto-rollback hooks.
  3. Write single close-report artifact with merge recommendation.
- Verify:
  - `python scripts/advisory_day_trial.py close --trial-id fasttrack_w1 --timeout-s 1800`
- Merge gate: close report includes decision + evidence links.
- Rollback: keep previous trial script behavior.

## PR-07 SQLite Backbone (Dual-Write)

- Branch: `feat/fasttrack-pr-07-sqlite-dual-write`
- Target files:
  - `lib/spark_db.py` (new)
  - `hooks/observe.py`
  - `lib/bridge_cycle.py`
  - `lib/cognitive_learner.py`
- Implement:
  1. Add active-state schema and migrations.
  2. Add dual-write from current path to SQLite.
  3. Add write verification counters.
- Verify:
  - targeted tests for DB write/read path
  - `python scripts/status_local.py`
- Merge gate: zero data-loss signal and stable runtime.
- Rollback: disable dual-write flag.

## PR-08 SQLite Read Shadow + Parity

- Branch: `feat/fasttrack-pr-08-sqlite-read-shadow`
- Target files:
  - `lib/advisor.py`
  - `lib/advisory_engine.py`
  - `scripts/trace_query.py`
  - parity report output path in `docs/reports/`
- Implement:
  1. Shadow-read SQLite against legacy read path.
  2. Emit parity diff report.
  3. Add thresholds for acceptable mismatch.
- Verify:
  - parity run on seeded replay sample
  - report generated with mismatch stats
- Merge gate: parity within threshold.
- Rollback: keep legacy read canonical.

## PR-09 Unified Noise Classifier Integration

- Branch: `feat/fasttrack-pr-09-unified-noise-classifier`
- Target files:
  - `lib/noise_classifier.py` (new)
  - `lib/meta_ralph.py`
  - `lib/cognitive_learner.py`
  - `lib/promoter.py`
- Implement:
  1. Single `classify()` API for noise decisions.
  2. Replace duplicate local rule sets in target modules.
  3. Preserve decision reason tags.
- Verify:
  - unit tests for classifier
  - replay checks for false-positive spikes
- Merge gate: noise performance stable or better.
- Rollback: switch call sites back to local rules.

## PR-10 Advisory Facade + Route Flags

- Branch: `feat/fasttrack-pr-10-advisory-facade`
- Target files:
  - `lib/advisory_engine.py`
  - `lib/advisor.py`
  - `lib/advisory_gate.py`
- Implement:
  1. Add facade pipeline: retrieve -> rank -> gate -> emit.
  2. Keep legacy adapter path for compatibility.
  3. Add route flags for canary rollout.
- Verify:
  - route-level smoke tests
  - advisory day snapshot under facade flag
- Merge gate: facade path stable in shadow.
- Rollback: route all traffic to legacy path.

## PR-11 Nightly One-Delta Self-Improve Loop

- Branch: `feat/fasttrack-pr-11-nightly-one-delta`
- Target files:
  - `scripts/run_advisory_retrieval_canary.py`
  - `lib/auto_tuner.py` or replacement loop module
  - `lib/production_gates.py`
- Implement:
  1. Constrain optimizer action set to max 12 knobs.
  2. Enforce one-delta-per-cycle.
  3. Persist policy ledger with replay/canary evidence.
- Verify:
  - dry-run cycle with no-op + one bounded delta
  - rollback path tested from backup
- Merge gate: full cycle produces deterministic report.
- Rollback: disable nightly loop scheduler.

## PR-12 Wave-1 Deletions + Config Packdown

- Branch: `feat/fasttrack-pr-12-wave1-deletions`
- Target files:
  - legacy modules replaced by PR-07/09/10
  - `config/tuneables.json`
  - `lib/tuneables_schema.py`
- Implement:
  1. Delete/disable only paths proven replaced and stable.
  2. Remove low-impact config variants.
  3. Update docs/contracts for removed paths.
- Verify:
  - full gate run:
    - `python scripts/production_loop_report.py`
    - `python scripts/memory_quality_observatory.py`
    - canary close report
- Merge gate: 7-day equivalent replay+canary stability evidence or approved risk waiver.
- Rollback: restore deleted modules from tagged checkpoint.

---

## 6) Agent Launch Template (Use In Each Agent Session)

Use this prompt in each agent terminal with PR-specific values:

```text
You are Agent <A|B|C> working only on <PR-ID>.
Worktree: <path>
Branch: <branch>
Scope files: <list>
Do not edit files outside scope.
Run verification commands for this PR.
Output:
1) Change summary
2) Verification summary
3) Risks and rollback note
```

---

## 7) Round Review and Merge Protocol

For each PR in a round:
1. Run required verification commands.
2. Perform focused review against PR card scope.
3. Enforce anti-spaghetti checklist:
   - dependency direction unchanged or improved
   - no duplicate utility reintroduction
   - no new global mutable state unless unavoidable and documented
   - no hidden side effects in helper/refactor commits
4. Enforce commit hygiene:
   - `6-12` commits target met (or justified exception)
   - all commits atomic and attributable
   - commit sequence includes tests and telemetry evidence
5. If pass: merge into `fasttrack/integration` with commit history preserved.
6. If fail: patch in same PR branch once; if still fail, defer PR and continue with other two.

After merging all passable PRs in round:
1. Tag checkpoint:
   - `git tag -a fasttrack-r<round>-done -m "FastTrack round <round> complete"`
2. Regenerate observability artifacts:
   - `python scripts/generate_observatory.py --force --verbose`
3. Start next round.

Integrator sanity commands:
1. `git log --oneline --decorate --graph -n 30`
2. `git diff --stat fasttrack-r<round>-done^ fasttrack-r<round>-done`
3. `python scripts/production_loop_report.py`

---

## 8) Today Completion Strategy

1. Target completion order: R1 -> R2 -> R3 -> R4.
2. If time pressure blocks full R4:
   - complete `PR-08` and `PR-11` first.
   - ship `PR-12` as minimal deletion subset only.
3. Do not force deletion PR if gates are red.
