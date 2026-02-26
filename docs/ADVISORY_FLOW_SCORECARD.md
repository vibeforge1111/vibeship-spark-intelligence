# Advisory Intelligence Flow Scorecard

Created: 2026-02-21
Scoring: 0 = missing, 1 = partial, 2 = present but weak, 3 = good, 4 = strong, 5 = production-ready.

This scorecard reviews the full intelligence flow for:
- `ingest -> distill -> transform -> retrieve -> synchronize -> reuse`
- not only developer-tool traces (`vibe_coding`), but all operational memory domains
- non-telemetry readiness (user reasoning, architecture, product, delivery, research, etc.)

## Part 1 — Intake, trace, and event normalization (20 questions)

| # | Question | Score | Why |
|---|---|---:|---|
|1|All hooks map canonical event types (`SessionStart`,`UserPromptSubmit`,`PreToolUse`,`PostToolUse`,`PostToolUseFailure`)?|5|Covered in `hooks/observe.py` with `EventType` mapping.|
|2|`trace_id` is attached end-to-end from ingress to downstream artifacts?|4|Mostly present via queue payload; some adapters still rely on best-effort recovery.|
|3|Tool and session metadata are consistently captured in every path?|4|Captured for hook-driven and queue-driven flows; edge cases still exist in some adapter-only emits.|
|4|User prompts get advisory metadata (`readiness`, `domain`, `content_len`)?|5|Added to `UserPromptSubmit` payload.|
|5|Tool events get advisory metadata for retrieval later?|5|Added to tool payload fallback (`command/path/query/text/content`).|
|6|`source` is normalized to avoid unknown/noisy values?|4|Defaults to `claude_code`; room to standardize more adapters.|
|7|Telemetry-only rows are weakly scoped and not over-captured?|4|Important tool telemetry still enters, then downstream noise gates are expected.|
|8|Large payloads are safe for hook speed (non-blocking)?|5|Intentional minimal work in hook; heavier extraction deferred.|
|9|Queue write failures fail open without dropping action context?|3|Best-effort behavior exists, but some rare failure paths still lose raw event fields.|
|10|Pre-action hooks keep latency guardrails and emit timing diagnostics?|4|Pre-tool budget metrics and timeout checks exist.|
|11|Pre-tool advisory errors do not block execution by default?|4|Fallback to best-effort legacy behavior with skip-on-exceeding budget handling.|
|12|Post-failure and post-success outcomes are both captured?|5|Both are captured and routed to advisor/advisory engine.|
|13|Intent capture runs for user prompt family in separate path as needed?|4|User prompt intent capture is invoked in observe and in memory capture layers.|
|14|Evidence of hook-level errors is persisted/logged?|4|`log_debug` calls exist for major errors.|
|15|Session end triggers final cleanup and autosave behaviors?|5|Outcome checks, promotion, and session-end hooks are implemented.|
|16|Adapter-specific custom formats are normalized before queue entry?|3|Main adapters map through sparkd well; adapter edge formats still vary.|
|17|Session ID derivation is stable across restart windows?|4|Used consistently via queue/session keys and bridge context paths.|
|18|Security/safety telemetry is captured separately from advisory payloads?|3|EIDOS control-plane exists; advisory payload currently focused on usefulness not full SIEM fields.|
|19|Capture path includes non-tool user cognition (`remember/decision/corrections`)?|5|Implemented via `cognitive_signals`, though more domain prompts can be added.|
|20|Intake is domain-aware enough to separate coding, system, and operations prompts?|4|Domain detection exists, could be expanded for more non-coding domains.|

**Part 1 total: 79 / 100**

### Part 1 recommendations
- P1: standardize adapter source normalization (`source` + `session_id`) before queue write so diagnostics are comparable across agents.
- P1: add explicit event-size cap + hash for oversized prompt/text payloads to preserve traceability without hook overhead.
- P2: ensure all non-hook adapters (stdin/stdin_ingest variants) apply the same advisory metadata enrichment path.

## Part 2 — Signal extraction, distillation, and insight storage (20 questions)

| # | Question | Score | Why |
|---|---|---:|---|
|1|User cognition extraction is domain-aware (`game_dev`,`marketing`,`product`,`ops`, etc.)?|5|`detect_domain` in `cognitive_signals.py` and pipeline-aware scoring exist.|
|2|Signals are filtered for minimum semantic signal (importance/quality)?|5|Importance scorer plus pattern set used before roast.|
3|Extraction path avoids synthetic test prompts or benchmark chatter?|5|`[PIPELINE_TEST` filter in cognitive extraction.|
4|Low-quality / garbled lines are pruned before storage?|5|Injection/garbage checks and advisory suppression gates exist.|
|5|Every stored insight has advisory transform metadata for downstream ranking?|4|Distillation paths improved. validate_and_store ensures Meta-Ralph quality gate runs on all writes; non-distilled user insights still depend on transform fallback quality in some spots.|
|6|User-derived cognitive signals are transformed into advisory format?|5|Task 5 now applies `transform_for_advisory` before add_insight.|
|7|Reliability and validation are separated from readiness signals?|5|`reliability` and `advisory_readiness` are both preserved.|
|8|`advisory_readiness` is persisted and backfilled for legacy insights?|5|Task 2 implemented backfill.|
|9|Conflict resolution avoids dropping validated learning when contradictory variants exist?|4|Conflict resolution exists with effective reliability and recency weighting.|
|10|Low-signal telemetry-style patterns are blocked from insight store?|4|Multiple suppression patterns and `_is_noise_evidence` / `_is_primitive` checks exist.|
|11|Actionability and reasoning are extracted into advisory-quality fields?|5|`distillation_transformer` computes dimensions and `unified_score`.|
|12|Suppressed distillations are retained for audit if needed?|4|Suppression prunes from advisory flow; quarantined insights now stored in `insight_quarantine.jsonl` for audit. Rejection telemetry persisted.|
|13|Semantic index writes happen on insight write (best effort) to support retrieval?|5|Cognitive indexing path in learner present.|
|14|Insight de-duplication avoids churn from counter variants?|5|Normalization and dedupe paths exist in learner and chip merger.|
|15|Promotion logic is conservative (reliability/times constraints)?|4|Promote-to-wisdom and promoter thresholds exist, but policy may still be too conservative in dynamic workflows.|
|16|Memory capture and cognitive capture remain separate to avoid double-counting?|4|Distinct flows exist; occasional overlap still needs tuning.|
|17|Per-category heuristics guard against operational/test noise?|4|Category + action-domain/backoff heuristics are in place.|
|18|Insights from e.g. external sources also receive advisory metadata on import?|3|Some sources add metadata on import; this is uneven across all sources.|
|19|Advisory-quality suppression reasons are stored for debugging?|5|Suppression reason is carried in advisory quality dict when generated.|
|20|Distillation pipeline is traceable from source event to final insight key?|4|Good traceability in logs and metadata, with few edge gaps in adapter-only paths.|

**Part 2 total: 84 / 100** (was 82, +2 from unified write path and quarantine store)

### Part 2 recommendations
- P1: ensure every path that creates stored cognition (including chip merges and eidos imports) produces advisory_quality + advisory_readiness for consistency.
- P1: add a lightweight source-level audit column in insights for `source_mode` (`tool|user|eidos|chip|mind`) to prevent silent mix bias.
- ~~P2: tighten suppression telemetry to preserve suppressed candidates in a dedicated "quarantine" store.~~ DONE: `insight_quarantine.jsonl` + `advisory_rejection_telemetry.json` now persist both quarantined insights and per-reason suppression counters.

## Part 3 — Advisory retrieval, ranking, and hot-path delivery (20 questions)

| # | Question | Score | Why |
|---|---|---:|---|
|1|Advisor prefilter respects minimum validation/reliability gates?|5|Eligibility filters are present and conservative.|
2|Retrieval uses advisory readiness as ranking signal?|5|`advisory_readiness` now first-class in `_rank_score` and prefilter.|
|3|Cross-domain filtering prevents wrong-domain guidance leakage?|5|Implemented in advisor with explicit domain gate.|
|4|Tool/prompt context influences domain-aware route profiles?|5|Tool/domain markers exist and influence routing config.|
|5|Prefilter and ranking include advisory quality (`unified_score` fallback)|5|Used via advisory-quality and fallback logic.|
|6|Cold paths handle empty/weak evidence safely?|4|Fallback behavior exists with profile-based controls.|
|7|Mind source inclusion follows staleness policy to avoid stale injection?|4|Staleness gates exist with override when empty.|
|8|Agentic fanout controls are bounded by deadline/rate cap?|5|Strong rate/deadline guardrails in tuneables.|
|9|Escalation rules are explicit for weak primary and high-risk contexts?|5|`minimal` and gate strategy parameters exist.|
|10|Semantic + lexical blend is explainable with diagnostic fields?|4|Route logs include reasons and timing; explainability can be further improved.|
|11|Low-quality/noisy results are filtered before synthesis/gate?|4|Quality/dedup and suppression logic exist, but some semantic edge cases remain.|
|12|Result provenance (`source`,`provider_path`,`route`) is retained for decision audits?|5|Recent improvements added provenance fields in logs.|
|13|Hot path avoids expensive full fusion when packet lookup succeeds?|5|Fallback-path intent to avoid heavy retrieval on hot path now present.|
|14|Fallback emission from advisory engine includes actionable command/check?|5|Actionability enforcement exists with next-check append. Emission safety is enforced via gate suppression, cooldowns, and route controls.|
|15|Legacy advisor compatibility still retained for resilience?|5|Legacy fallback still available behind safeguards.|
|16|Contextual recency aging is applied to avoid stale recommendations dominating?|4|Effective recency and reliability flows are present.|
|17|Duplicate recommendations are de-duplicated across sources?|4|Cross-source de-dupe and caps exist, but collisions still occur in rare edge cases.|
|18|Synthesis output is bounded (length/policy) while preserving signal density?|4|Bounded by templates and synthesis policies; could be more deterministic.|
|19|Delivery channel behavior differs for packet/live modes without quality regression?|4|Modes exist; packet telemetry to diagnose deltas still needs more robust A/B counters.|
|20|Cross-tenant or cross-project leakage is prevented in retrieval ranking?|4|Adapter-level separation exists; additional strict tenant-like guard checks advisable for mixed contexts.|

**Part 3 total: 82 / 100**

### Part 3 recommendations
- P1: add a strict rule: if source includes suppressed/noisy evidence in top-k, hard-drop before user-facing merge.
- P1: tighten provenance score explanation: expose top-3 reason terms (`why`) in a deterministic schema.
- P2: add a cross-run stability metric for packet vs live advice divergence.

## Part 4 — Memory fusion, evidence bundling, and sync projection (20 questions)

| # | Question | Score | Why |
|---|---|---:|---|
|1|Fusion covers all required memory sources (cognitive, eidos, chips, outcomes, orchestration, mind)?|5|Sources listed and merged in `build_memory_bundle`.|
|2|Fusion returns declared absence when all sources empty (`memory_absent_declared`)?|5|Implemented for deterministic fallback behavior.|
3|Source availability failures are explicit (`missing_sources` + errors)|5|Available/error summary is returned in bundle metadata.|
4|Suppressed advisory entries are removed from memory bundle?|5|Suppressed metadata is checked and filtered.|
|5|Cross-source dedupe works on normalized evidence text?|5|Normalized dedupe exists by text key.|
|6|Noise and telemetry markers are excluded in each source collector?|5|Noise checks and telemetry markers are implemented.|
|7|Evidence confidence combines quality, relevance, and confidence|5|Composite scoring used in chip/outcome/chips collectors.|
|8|Memory bundle includes advisory readiness signals for ranking?|5|Task 6 now injects/uses `advisory_readiness`.|
|9|Tool intent text is tokenized for relevance scoring robustly?|4|Tokenization exists; domain-specific token weighting still limited.|
|10|Outlier low-confidence rows are retained for offline diagnostics?|4|Dropped low-signal rows are usually omitted in online path; quarantine store is limited.|
|11|Mind source participates in bundle when include_mind=True?|4|Optional include path exists; not always on by default.|
|12|Adapter-specific memory sources include evidence confidence normalization?|4|Most adapters normalize; some still diverge in confidence scale assumptions.|
|13|Context sync uses diagnostic evidence counts and selected item caps?|5|Limits and diagnostics are present in sync path.|
|14|Sync projections are prioritized by advisory-readiness after conflict filters?|4|Readiness now influences advisory ranking and context sync order.|
|15|Promoted docs and chip highlights are blended without duplicate injection?|5|Dedupe and duplicate prevention implemented.|
|16|Project context filtering prevents irrelevant context bleed?|4|Project context filtering exists with dedupe and override logic.|
|17|Sync adapters are fail-soft across failures (core/optional separation)?|5|Adapter policy with fallback states is defined.|
|18|Adapters receive same advisory quality fields for downstream analysis?|3|Sync writes currently consume formatted text, not full advisory payload.|
|19|Cross-partner outputs (openclaw/clawdbot/exports) keep stable schema text boundaries?|4|Schema is stable text style; payload fields for machine consumers are limited.|
|20|Human-facing sync output avoids raw telemetry and noise while staying complete?|4|Quality and low-value gates applied; occasional noisy operational snippets still slip through.|

**Part 4 total: 81 / 100**

### Part 4 recommendations
- P1: emit a machine-readable advisory artifact (`advisory_payload.json`) alongside text sync for each adapter to consume readiness and confidence.
- P1: include advisory_readiness in all fusion sources (mind/offline queue rows) before score ordering.
- P2: add one-step “high-noise quarantine” sink to retain dropped rows for audit.

## Part 5 — Outcomes, feedback, and system quality governance (20 questions)

| # | Question | Score | Why |
|---|---|---:|---|
|1|Post-tool outcomes feed advisory engine and learner consistently?|5|Both legacy and engine outcome callbacks are wired.|
|2|Recovery/negative outcomes feed reliability and advisory scores?|5|Failure/success outcomes adjust reliability and advisor outcomes flows.|
|3|Advice outcome IDs are tracked and attributed to insight keys?|4|Meta-Ralph tracking exists; trace alignment can still be improved in some paths.|
|4|Contrast-based effectiveness exists (tool with advice vs without advice)?|5|`compute_contrast_effectiveness` path exists in advisor.|
|5|Negative outcomes with prior advice are explicitly marked as non-helpful?|5|Failure branch records explicit outcome as not helpful when advice existed.|
6|Positive outcomes without explicit advice do not falsely credit advice?|5|Outcome path separates unknown/no advice cases.|
|7|Effectiveness counters can be repaired/normalized for drift?|4|Repair helpers exist.|
8|Outcome checkpoints are requested in session end conditions?|4|Checkpoint logic exists with env toggles.|
|9|Feedback loops can capture explicit user advice feedback?|5|Explicit feedback endpoints and outcome recorders exist.|
|10|Cross-source outcome telemetry is retained for long-tail learning?|4|Stored in Meta-Ralph; dashboards can still lag on aggregation latency.|
11|Tuneables expose advisory/feedback thresholds for runtime control?|5|Large tuneable surface exists across advisor and advisory engine.|
12|Governance has clear precedence when multiple guidance contracts conflict?|4|Contract precedence work exists in other task backlog; partial hardening still pending.|
13|No silent default that drops all negative signals in high noise windows?|4|Noise handling exists, but heavy suppression can hide some negative evidence.|
14|Dashboard tracks advisory delivery states (`live/fallback/blocked`)?|5|Delivery badge and logs exist.|
15|Task-level metrics include elapsed, route, and envelope details?|5|Route logs include timing and reasons.|
16|Governance separates telemetry noise from strategic memory growth?|4|Noise suppression exists but could be stricter by source class.|
17|Error handling in feedback updates is resilient and non-blocking?|5|Most feedback tracking uses best-effort try/except.|
|18|Quality debt/repair scripts exist and are runnable in maintenance windows?|4|Repair helpers exist but are not fully scheduled.|
|19|Operational docs are aligned with runtime defaults and fallback behavior?|4|Docs track many defaults; some contract docs still marked stale (tasked in other backlog phase).|
|20|End-to-end audit trail allows “why this advice was shared here, now” explanation?|4|Most of the trail exists, but a single consolidated explanation object is still missing.|

**Part 5 total: 81 / 100**

### Part 5 recommendations
- P1: add a consolidated “advisory decision ledger” per retrieval event (`why_selected`, `why_excluded`, `ready_score`, `domain_match`) to support true explainability.
- P1: close the open contract clarity gap (`bridge` precedence and contract consistency docs) before relying on docs for operations.
- P2: schedule `repair_effectiveness_counters()` and `compute_contrast_effectiveness` into routine maintenance.

## Consolidated score

- Part 1: 79/100
- Part 2: 82/100
- Part 3: 82/100
- Part 4: 81/100
- Part 5: 81/100

**Overall: 405 / 500 (81.0%)**

## Top 10 cleanup/optimization priorities (for the next loop)

1. **Task 7 (done):** standardize advisory readiness/quality propagation for all memory sources, including mind/offline queue rows.
2. Add per-source `advisory_payload` schema output in sync adapters for deterministic downstream consumption.
3. Persist advisory suppression rows in a compact quarantine store to avoid losing rejected-but-useful patterns.
4. Normalize adapter `source`/`session_id` before write for reliable cross-adapter diagnostics.
5. Expand domain markers beyond coding/UI to include ops, research, architecture, governance, and product management consistently.
6. Strengthen cross-domain guardrails for recommendations with same confidence/urgency across unfamiliar domains.
7. Add explicit telemetry-vs-memory quality split in all scoring functions.
8. Record negative outcomes with advisory IDs for every advice path (engine packet + legacy fallback).
9. Introduce one daily health report from advisory retrieval route logs: top sources, miss reasons, and fallback ratio.
10. Convert all “best effort” metadata fields into explicit schema docs and lint checks (contract integrity).
