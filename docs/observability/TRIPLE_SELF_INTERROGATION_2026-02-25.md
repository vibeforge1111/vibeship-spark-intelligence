# Triple Self-Interrogation (Deep, SOTA Lens)

Date: 2026-02-25
Window: last 24h
Method: Evidence-first + comparison to SOTA self-improving intelligence systems

---

## Baseline Metrics Used

- Memory observatory grade: **RED (0.586)**
- Capture noise ratio: **0.356**
- Context p50: **53 chars**
- Semantic low-sim ratio (<0.1): **0.235**
- Advisory events: **500**
- Advisory emit rate: **0.076**
- No-emit ratio: **0.742**
- Noise burden: **0.744** (breach > 0.65)
- GAUR: **0.2405** (passes >=0.20)

SOTA reference posture:
- capture noise ratio < 0.20
- context p50 >= 120 (for condition+action+reason retention)
- semantic low-sim ratio < 0.15
- advisory emit rate usually 0.20–0.40 in strict-but-healthy systems
- suppression dominated by quality policy, not broad dedupe

---

## A) Memory Quality — 12 Q&A

1. **Are we capturing too much garbage?**
   - Data: noise ratio 0.356.
   - Verdict: **Yes (bad)**.
   - SOTA gap: +15.6 points above target.
   - Action: tighten noise regex + source-level blocks.

2. **Are we missing high-signal memories?**
   - Data: current detector shows 0 missed high-signal in 24h (likely under-detection).
   - Verdict: **Measurement weak**.
   - SOTA gap: needs stronger recall audit.
   - Action: add semantic missed-candidate detector.

3. **Is context rich enough for future retrieval quality?**
   - Data: context p50 53.
   - Verdict: **No**.
   - SOTA gap: ~67 chars below minimum useful median.
   - Action: expanded context capture to 320 chars (done), validate daily shift.

4. **Do we over-store evidence blobs?**
   - Data: mind queue sample avg ~780 chars with heavy Evidence blocks.
   - Verdict: **Yes**.
   - SOTA gap: too much raw transcript, not distilled memory.
   - Action: evidence compaction before persistence.

5. **Is memory store skewed to generic categories?**
   - Data: wisdom/meta-heavy profile.
   - Verdict: **Yes**.
   - SOTA gap: underweight tactical execution memory.
   - Action: category balancing policy.

6. **Are duplicates under control?**
   - Data: duplicate ratio low (~0.041 in store), but recurring generic keys still dominate retrieval.
   - Verdict: **Partially**.
   - Action: semantic de-dup on meaning, not only text.

7. **Are noise filters in retrieval compensating for noisy ingest?**
   - Data: retrieval has noise filters, yet low-sim ratio still 0.235.
   - Verdict: **Not enough**.
   - Action: move more filtering to ingest (already started).

8. **Do we measure memory utility downstream?**
   - Data: no robust utility-per-memory scoreboard yet.
   - Verdict: **Gap**.
   - SOTA gap: missing outcome-linked utility loop.
   - Action: memory→advisory→outcome linkage metric.

9. **Is sync backlog acceptable?**
   - Data: offline queue ~9.9k.
   - Verdict: **No**.
   - SOTA gap: too much deferred memory syncing.
   - Action: queue burn-down SLO + stale-trim policy.

10. **Is ingest threshold strict enough?**
   - Data: thresholds recently raised to 0.72/0.60.
   - Verdict: **Improving**.
   - Action: observe 3-day drift before further bump.

11. **Do we capture user preference decisions reliably?**
   - Data: some captured, but still drowned by system scaffolding.
   - Verdict: **Mixed**.
   - Action: decision-intent weighted trigger lane.

12. **Are we improving daily, measurably?**
   - Data: daily observatory now live.
   - Verdict: **Yes (infrastructure)**, quality still red.
   - Action: 7-day target run with hard gates.

Memory Bottom Line: ingestion quality is still below SOTA, but now instrumented and patched in the right direction.

---

## B) Advisory Emissions — 12 Q&A

1. **Is emission rate healthy?**
   - Data: 0.076.
   - Verdict: **Too low**.
   - SOTA gap: expected healthy strict range 0.20–0.40.
   - Action: reduce over-suppression without reintroducing noise.

2. **Are we suppressing mostly for good reasons?**
   - Data: no-emit 74.2%; heavy dedupe and generic-read suppression.
   - Verdict: **Over-suppression**.
   - Action: refine dedupe scope per session/task plane.

3. **Is global dedupe excessive?**
   - Data: dominant in suppression traces.
   - Verdict: **Yes**.
   - Action: shift from global to contextual dedupe TTL.

4. **Are advisory sources diverse and useful?**
   - Data: cognitive dominates; eidos secondary; semantic lower.
   - Verdict: **Skewed**.
   - Action: source utility weighting by outcome success.

5. **Do emitted advisories have strong actionability?**
   - Data: actionability often synthetically added; not always effective.
   - Verdict: **Mixed**.
   - Action: promote effective-actionability metric over nominal actionability.

6. **Is packet freshness a risk?**
   - Data: packet routes dominate no-emit with stale-like repeats.
   - Verdict: **Likely risk**.
   - Action: stronger packet freshness/invalidations.

7. **Is retrieval latency acceptable?**
   - Data: synth latencies can be multi-second (avg ~4.1s emitted, p50 high).
   - Verdict: **Borderline**.
   - Action: cheaper first-pass synthesis lane + fallback.

8. **Are we emitting repeated generic advice?**
   - Data: repeated reasons and repeated key patterns present.
   - Verdict: **Yes**.
   - Action: anti-generic scoring penalty.

9. **Do intent families get fair treatment?**
   - Data: emergent/deployment paths differ; exploration suppressions common.
   - Verdict: **Policy imbalance**.
   - Action: per-intent suppression policy tuning.

10. **Is quality gate calibrated to current phase?**
   - Data: high suppression in discovery/exploration.
   - Verdict: **Too strict for current mode**.
   - Action: adaptive strictness by phase.

11. **Are we learning from no-emit outcomes?**
   - Data: logs rich, but not auto-converted into gate optimization loop.
   - Verdict: **Gap**.
   - Action: nightly suppression-mining -> suggested gate changes.

12. **Can we improve emissions without raising noise burden?**
   - Data: possible but needs constrained gate tuning.
   - Verdict: **Yes, with controlled experiments**.
   - Action: A/B 3 gate tweaks, monitor noise burden + GAUR jointly.

Advisory Bottom Line: currently too suppressed; SOTA path is precision-preserving de-over-suppression.

---

## C) Website Experience + Onboarding Flow — 12 Q&A

(Important: direct web analytics instrumentation is currently weak; several answers are confidence-limited and call for telemetry gaps to be closed.)

1. **Do we know exact onboarding drop-off points?**
   - Data: not fully instrumented.
   - Verdict: **No (telemetry gap)**.
   - Action: step funnel events required now.

2. **Do we know time-to-first-value on web onboarding?**
   - Data: not reliable.
   - Verdict: **No**.
   - Action: add TTFV timer from start->first successful advisory.

3. **Where is highest friction?**
   - Data: recurring qualitative complaints around setup/config complexity.
   - Verdict: **Likely setup/model config stages**.
   - Action: progressive onboarding modes.

4. **Is copy clarity strong for non-technical users?**
   - Data: docs are thorough but operationally heavy.
   - Verdict: **Mixed (too dense)**.
   - Action: plain-language short path + expandable advanced details.

5. **Are errors actionable?**
   - Data: many operational errors still technical.
   - Verdict: **Not enough**.
   - Action: error-to-fix mapping with one-click remediation.

6. **Do users get overwhelmed by early options?**
   - Data: yes in strategy/config/model layers.
   - Verdict: **Yes**.
   - Action: hide advanced controls until baseline success.

7. **Is LLM lane choice understandable?**
   - Data: architecture exists; UX for lane choice still emerging.
   - Verdict: **Partial**.
   - Action: explicit lane matrix in onboarding UI.

8. **Are we measuring behavior vs assumption?**
   - Data: sparse web telemetry.
   - Verdict: **No**.
   - Action: onboard analytics schema + weekly behavior audit.

9. **Do users trust the setup flow?**
   - Data: trust drops when status surfaces disagree.
   - Verdict: **Fragile trust**.
   - Action: single-source onboarding health card.

10. **What one fix gives max UX gain tomorrow?**
   - Verdict: add `onboard verify --strict` score + clear pass/fail remediation.

11. **What should be progressive disclosure?**
   - Verdict: model strategy, budget policy, advanced tuneables.

12. **What should be simplified/removed now?**
   - Verdict: early-phase optional complexity and non-essential knobs.

Website/Onboarding Bottom Line: SOTA-level UX requires telemetry-first funnel visibility + progressive complexity.

---

## Cross-Section Priority Actions (Start Today)

1. Memory ingest precision sprint (noise ratio <0.30 within 72h).
2. Dedupe policy refactor experiment (lift emit rate while keeping noise burden <=0.65).
3. Onboarding telemetry schema (step funnel, TTFV, error class, recovery success).
4. Daily suppression-to-fix recommendations in nightly report.
5. Weekly SOTA delta review against these targets.

## 7-Day Target Snapshot

- Capture noise ratio: **0.356 -> <=0.25**
- Context p50: **53 -> >=100**
- Advisory emit rate: **0.076 -> >=0.14** (phase-safe)
- Semantic low-sim ratio: **0.235 -> <=0.18**
- Onboarding telemetry coverage: **baseline -> >=90% step coverage**
