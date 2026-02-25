# Obsidian Observatory + Pulse Dashboard Self-Interrogation (SOTA Lens)

Date: 2026-02-25
Mode: evidence-first, least-resistance implementation (reuse existing systems first)

## Live Data Anchors

- Observatory snapshot:
  - queue_pending: 2826
  - advisory emit rate: 9.0%
  - meta pass rate: 3.0%
- Pulse live endpoints:
  - `/api/learning` = unavailable/zeros
  - `/api/mission` = unavailable/zeros
  - `/api/outcomes` has data (3000 outcomes, 2387 unlinked)
  - `/api/predictions` has data (42 predictions)
  - `/api/eidos/distillations` has rich effectiveness (retrieved 12250, used 2353, helped 1988)
  - `/api/eidos/compounding` shows weak compounding and negative memory delta

SOTA reference for self-improving intelligence UIs:
- Fewer vanity metrics, more action-loop metrics
- Unified metric definitions across surfaces
- Every panel tied to next action and owner
- Dead panes hidden/degraded clearly

---

## A) Obsidian Observatory — 12 Questions + Answers

1. **Does Observatory answer “what should I do now?” in under 60 seconds?**
   - Answer: Partially. Great structure, but actionability is diffuse.
   - Gap: too many pages, weak hard-fail triage path.

2. **Are core metrics coherent with Pulse/CLI?**
   - Answer: Not consistently (queue and emit values diverge by surface/time).
   - Gap: no canonical metric contract page.

3. **Does `start_here.md` prioritize the highest-risk blockers?**
   - Answer: Not enough. It’s navigational, not criticality-ranked.
   - Gap: no explicit “Top 3 red risks now” block.

4. **Is `changes_since_last_regen.md` operationally useful?**
   - Answer: Useful for deltas, weak on significance.
   - Gap: no “delta impact” label (noise, stability, UX risk).

5. **Are stage pages too broad for incident triage?**
   - Answer: Sometimes. High information, low urgency ordering.
   - Gap: needs “what to run now” command block per failure mode.

6. **Do we expose suppressed advisory causes clearly?**
   - Answer: Yes in deep pages, not in front-door dashboard.
   - Gap: suppression concentration should be in flow header.

7. **Is memory quality visible as first-class signal?**
   - Answer: Newly added observatory exists, but not wired into flow front page.
   - Gap: memory quality score absent from top health table.

8. **Do we track metric freshness confidence?**
   - Answer: weakly.
   - Gap: no per-metric freshness/source badge in key tables.

9. **Is operator load minimized?**
   - Answer: Not yet. Too much drill-down for simple answers.
   - Gap: no one-page “operator daily board” synthesized from all sections.

10. **Can we identify regressions without reading multiple files?**
   - Answer: Partially with `changes_since_last_regen`, but not full-system.
   - Gap: no cross-domain regression ledger in observatory root.

11. **Do we know what *not* to trust right now?**
   - Answer: No explicit confidence annotations on sections.
   - Gap: missing “low-confidence metrics” table.

12. **SOTA verdict on Observatory today?**
   - Answer: **Strong documentation substrate, medium operational usability.**
   - Upgrade path: improve synthesis, not more raw pages.

---

## B) Pulse Dashboard — 12 Questions + Answers

1. **Does Pulse prioritize useful over pretty?**
   - Answer: Mixed. Strong visuals; utility panels include dead/empty views.

2. **Are all major tabs fed with live data?**
   - Answer: No. `/api/learning` and `/api/mission` are unavailable/zero while related data exists elsewhere.

3. **Do “learning funnel” numbers reflect actual system learning?**
   - Answer: No (zeros), despite rich distillation effectiveness in `/api/eidos/distillations`.

4. **Is validation tab trustworthy?**
   - Answer: No, in current form. Outcomes/predictions exist but presentation is inconsistent.

5. **Can operators act from the dashboard without opening logs?**
   - Answer: Not reliably.
   - Gap: no “Next Action” per red metric.

6. **Are advisory suppression causes visible in Pulse?**
   - Answer: Not prominently.
   - Gap: show top suppression reason + ratio in main panel.

7. **Is memory effectiveness represented honestly?**
   - Answer: Compounding endpoint currently shows weak/no compounding and negative memory delta; this should be surfaced as RED truth.

8. **Is there feature bloat relative to operational value?**
   - Answer: Yes. Some panes are decorative while critical links are hidden.

9. **Do we have a canonical “health mode” view?**
   - Answer: Not yet.
   - Gap: should default to a no-BS operations view (few metrics, direct commands).

10. **Are we reusing existing backend data enough?**
   - Answer: No. Existing rich endpoints are underused by UI.

11. **SOTA verdict on Pulse today?**
   - Answer: **Visually strong, operationally underwired.**

12. **Fastest path to usefulness?**
   - Answer: Rewire existing endpoints into existing cards; hide dead cards until live.

---

## C) Unified Least-Resistance Implementation Plan (No New Big Systems)

## Principle
1) Reuse existing data + pages first.
2) Tune thresholds/layout second.
3) Add minimal glue code only for missing joins.
4) New systems only if proven necessary.

## Phase 1 (Today–48h): Rewire, don’t rebuild

1. **Pulse: Wire LEARN tab to existing distillation effectiveness**
   - Use `/api/eidos/distillations.effectiveness` for retrieved/used/helped.
   - Hide any learning widgets still returning unavailable.
   - No new model/infra needed.

2. **Pulse: Build “No-BS mode” using existing endpoints**
   - show only: noise burden, GAUR, emit rate, top suppression, queue debt, unlinked outcomes.
   - map each to one command/action.

3. **Observatory: Add top-of-page “Operator Now” block**
   - Inject into `flow.md` generation:
     - top 3 blockers
     - next actions
     - confidence/freshness markers.

4. **Observatory: Add memory quality card in System Health**
   - Reuse `_observatory/memory_quality_snapshot.json` already generated.

## Phase 2 (3–5 days): Tighten coherence

5. **Metric contract page (single source definitions)**
   - one page: field name, formula, source file, refresh cadence.
   - observatory + pulse point to this.

6. **Suppression transparency strip in both surfaces**
   - top suppression reason and ratio from advisory engine logs.

7. **Cross-surface drift checker (daily)**
   - compare key metrics across CLI/Pulse/Observatory and flag mismatch.
   - small script, no new service.

## Phase 3 (Week 2): Daily optimization loop

8. **Nightly 5-section self-interrogation in report**
   - memory
   - advisory
   - website/onboarding
   - observatory usability
   - pulse utility

9. **Action ledger with owner+ETA+proof link**
   - one table, append daily.

10. **Prune low-value widgets**
   - if widget stays empty/unavailable for 7 days, hide by default.

---

## D) Concrete KPI Targets (7-day)

- Pulse dead widgets visible by default: **0**
- Observatory operator triage time: **< 90 sec**
- Cross-surface metric drift incidents/day: **<= 1**
- Suppression transparency coverage: **100% of daily reports**
- Memory quality card present in flow front page: **yes**

---

## E) Immediate Next Actions (start now)

1. Rewire Pulse LEARN tab from `/api/eidos/distillations.effectiveness`.
2. Hide unavailable `/api/learning`/`/api/mission` widgets behind degraded state labels.
3. Add Observatory “Operator Now” + memory quality card to flow generator.
4. Add nightly sections for Observatory + Pulse self-interrogation.

Bottom line: We can get major utility gains **without building new big code**, by wiring and re-prioritizing what already exists.
