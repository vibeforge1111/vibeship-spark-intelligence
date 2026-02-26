# Spark Learning Systems -> New Spark Integration Map

Date: 2026-02-24  
Spark core repo: `vibeship-spark-intelligence` (`main`)  
Learning systems repo reviewed: `spark-learning-systems` @ `origin/master` `c06272a`

## Goal

Connect learning systems to the new Spark write/read safety model without reintroducing bypasses:

- No direct writes to `~/.spark/cognitive_insights.json`.
- No direct writes to `~/.spark/tuneables.json` from external systems.
- Distillation writes must use the same quality/validation contract as Spark core.
- All external writes must be auditable and reversible.

## New bridge contract (implemented in Spark core)

- Safe insight ingress:
  - `lib/learning_systems_bridge.py:64` `store_external_insight(...)`
  - Routes through `lib/validate_and_store.py:99` `validate_and_store_insight(...)`
  - Writes audit log to `~/.spark/learning_systems/insight_ingest_audit.jsonl`
- Tuneable proposal ingress:
  - `lib/learning_systems_bridge.py:117` `propose_tuneable_change(...)`
  - Queues proposals in `~/.spark/learning_systems/tuneable_proposals.jsonl`
  - Does not mutate runtime tuneables directly
- CLI for external repo usage:
  - `scripts/learning_systems_bridge.py`
  - `store-insight`, `propose-tuneable`, `list-proposals`

## System-by-system mapping

| System | Current mutation path (learning repo) | New Spark hook | Risk | Rollout flag | Required test |
|---|---|---|---|---|---|
| 01 Distillation Accelerator | `01-distillation-accelerator/src/accelerator.py:174` (`write_distillation`) | Keep write path, but add Spark-side distillation quality guard before persist | Medium | `LS_SYSTEM01_WRITE=0/1` | invalid distillation rejected, valid accepted |
| 04 Retrieval Gauntlet | `04-retrieval-gauntlet/src/tuner.py:349-370` direct tuneables write | `propose-tuneable` only (no direct write) | High | `LS_SYSTEM04_TUNE_WRITE=0` | proposal queued, no tuneables file mutation |
| 05 Code Pattern Observatory | `05-code-pattern-observatory/src/observatory.py:332-345` direct cognitive write | `store-insight` | High | `LS_SYSTEM05_INSIGHT_WRITE=0` | every emitted insight appears in audit + cognitive store |
| 07 Prompt Evolution Lab | `07-prompt-evolution-lab/src/lab.py:389-399` direct cognitive write | `store-insight` | High | `LS_SYSTEM07_INSIGHT_WRITE=0` | refined insights pass Meta-Ralph/noise gates |
| 08 Self-Contradiction Resolver | `08-self-contradiction-resolver/src/resolver.py:291-303` direct overwrite | Stage changes as proposals + Spark-owned apply phase | Critical | `LS_SYSTEM08_APPLY=0` | partial apply rollback + no corruption under crash |
| 09 Cross-Domain Synthesis | `09-cross-domain-synthesis/src/engine.py:328` (`write_distillation`) | Keep with distillation guard + audit | Medium | `LS_SYSTEM09_WRITE=0/1` | distillation write includes source trace |
| 12 Goal Genesis Lab | `12-goal-genesis-lab/src/lab.py:138-158` direct cognitive write | `store-insight` | High | `LS_SYSTEM12_INSIGHT_WRITE=0` | confidence/category preserved through bridge |
| 18 Consciousness Growth Tracker | `18-consciousness-growth-tracker/src/tracker.py:264-275` direct cognitive write | `store-insight` | High | `LS_SYSTEM18_INSIGHT_WRITE=0` | idempotent key behavior validated |
| 22 Code Evolution Lab | `22-code-evolution-lab/src/lab.py:238-239` targets `~/.spark/tuneables.json` | Route tuneables changes via proposal queue + branch workflow | High | `LS_SYSTEM22_TUNE_WRITE=0` | no direct runtime tuneables edits |
| 26 Executive Loop | `26-executive-loop/src/executor.py:221-265` direct tune write; `loops/evolution_router.py:356-368` direct fallback | Keep branch path; disable direct-write fallback in production | Critical | `LS_SYSTEM26_DIRECT_WRITE_FALLBACK=0` | branch-only mutation; fallback blocked |

## What is safe to connect immediately

- Read-only systems consuming queue/advisor/eidos/cognitive stores.
- Insight-producing systems that can switch to `store-insight`.
- Tuneable-producing systems only in proposal mode.

## What should not be connected directly yet

- Any path that overwrites full cognitive store JSON (`system 08` pattern).
- Any path that writes runtime tuneables directly (`systems 04, 22, 26 fallback`).
- Any mutation path that has no audit record and no rollback record.

## Rollout order

1. Shadow mode in learning repo:
   - keep existing logic, but call `scripts/learning_systems_bridge.py ...` in parallel and compare outputs.
2. Cut over insight writes:
   - systems `05`, `07`, `12`, `18` -> `store-insight`.
3. Cut over tuneable mutations:
   - systems `04`, `22`, `26` -> proposal queue only.
4. Add distillation guard layer for systems `01` and `09`.
5. Enable production flags one system at a time with rollback defaults off.

## Observatory updates required

- Add explore pages for:
  - `~/.spark/learning_systems/insight_ingest_audit.jsonl`
  - `~/.spark/learning_systems/tuneable_proposals.jsonl`
- Add flow node:
  - `learning_systems_bridge` between external systems and Stage 5/6.
- Add counters:
  - `ingest_attempted`, `ingest_stored`, `ingest_rejected`, `proposal_queued`.

## Pulse updates required

- Add panel: **Learning Systems Bridge**
  - Recent insight ingests (stored vs rejected).
  - Pending tuneable proposals by system.
  - 24h error/rejection trend.
- Add alert conditions:
  - rejection rate spike (`>40%` for 1h),
  - proposal backlog age (`oldest pending >24h`),
  - bridge disabled while systems are active.

## Documentation updates required

- Update `docs/INTELLIGENCE_FLOW_EVOLUTION.md` with external ingress contract.
- Update `docs/OBSIDIAN_OBSERVATORY_GUIDE.md` with new learning bridge pages.
- Update learning-systems runbooks to use:
  - `python scripts/learning_systems_bridge.py store-insight ...`
  - `python scripts/learning_systems_bridge.py propose-tuneable ...`

