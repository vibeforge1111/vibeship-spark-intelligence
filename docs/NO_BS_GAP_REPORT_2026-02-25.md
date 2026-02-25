# Spark Intelligence — No-BS Gap Report (Deep Architecture + Onboarding + LLM Strategy)

**Date:** 2026-02-25 (Asia/Dubai)  
**Analyst mode:** no-BS / evidence-first  
**Scope:** stability, scalability, UX/operability, observability/watchtowers (Pulse + Observatory/Obsidian), onboarding friction, strategic LLM usage model

---

## 1) Brutal Executive Verdict

Spark Intelligence is improving in core engineering discipline, but it is **not production-ready as a predictable system** yet.

You are in the **dangerous middle phase**:
- architecture is now sophisticated enough to create hidden coupling failures,
- but guardrails/observability are not yet strict enough to prevent regressions from escaping.

**Current posture:** **LIMITED READY** (for controlled operators), **NOT READY** (for broad frictionless onboarding scale).

---

## 2) Evidence Snapshot (What the system is actually saying)

### 2.1 KPI scorecard (24h + 7d)
From `scripts/carmack_kpi_scorecard.py --window-hours 24/168 --alert-json`:
- **Status:** `breach`
- **Breach:** `noise_burden_high`
- **Noise burden:** `0.758` (threshold `<= 0.65`) ❌
- **GAUR:** `0.237` (threshold `>= 0.20`) ✅
- **Bridge heartbeat freshness:** healthy ✅
- **Watchdog:** `running=false` ❌

### 2.2 Runtime status snapshot
From `python cli.py status`:
- Cognitive insights: **54**
- Synced to Mind: **29**
- **Offline queue: 14,469** ❌ (severe debt)
- Prediction KPIs (7d):
  - ratio: `0.02`
  - unlinked outcomes: **2,386** ❌
  - coverage: `34.8%`
- Validation loop last run: stale-ish (multi-thousand seconds)

### 2.3 Production loop gates
From `scripts/production_loop_report.py`:
- **Gate status: NOT READY (14/19 pass)**
- Critical fails:
  - strict acted_on rate `3.9%` (target `>=20%`) ❌
  - strict trace coverage `10%` (target `>=50%`) ❌
  - advisory store readiness `0.0` (target `>=0.40`) ❌
  - advisory store freshness `0.0` (target `>=0.35`) ❌
  - meta-r_alph quality band `8.1%` (target `30–60%`) ❌

### 2.4 Observatory snapshot
From `_observatory/.observatory_snapshot.json`:
- Queue pending: **2,826**
- Meta pass rate: **3.0%**
- Advisory emit rate: **9.0%**

> **Important inconsistency:** queue-related metrics disagree across surfaces (`queue_depth=0` vs `queue_pending=2826` vs `offline_queue=14469`). This itself is a high-priority observability failure.

---

## 3) Architecture Reality Check (Where we are truly strong vs fragile)

## 3.1 Ingestion / queue / bridge
**Strengths**
- Queue and bridge process are active and heartbeat-fresh.
- Event ingestion validity appears stable (recent valid ratio high).

**Fragilities**
- Multi-queue debt (event queue, pending queue, offline mind queue) is not harmonized in operator reporting.
- Backlog visibility is fragmented; operators can think things are healthy when they’re not.

**No-BS verdict:** ingest path is alive, but queue truth is not unified.

## 3.2 Quality gate + distillation
**Strengths**
- Meta-Ralph and EIDOS architecture remains conceptually strong.
- Distillation volume exists (not dead system).

**Fragilities**
- Quality pass band is far below target in current gating report.
- Distillation/advisory usefulness is not mapping cleanly to strict action outcomes.

**No-BS verdict:** quality machinery exists, but conversion to reliable real-world effect is weak.

## 3.3 Advisory retrieval + delivery
**Strengths**
- Advisory store effectiveness metric is above threshold in one dimension.
- Emission controls and dedupe are active.

**Fragilities**
- Readiness/freshness of advisory packets are both at 0.0 in production gates.
- High policy suppression + low strict acted-on indicates retrieval/delivery timing mismatch or stale packet quality.

**No-BS verdict:** advisory stack is functional but not operationally trustworthy under strict attribution.

## 3.4 Outcome linkage / learning closure
**Strengths**
- Outcome tracking infra exists in multiple places.
- Strict policy mode is enabled (good discipline intent).

**Fragilities**
- Unlinked outcomes are very high.
- Strict trace coverage is 10%; this means most real impacts are not reliably attributable.

**No-BS verdict:** system is learning, but weakly grounded; confidence claims are ahead of attribution quality.

## 3.5 Watchtowers & observability (Pulse/Obsidian)
**Strengths**
- Observatory generation and delta pages exist; useful operationally.
- Stage-level narrative docs are strong and discoverable.

**Fragilities**
- Watchdog off while system claims are “healthy” in other surfaces.
- Conflicting metrics across status, KPI, and observatory snapshots.
- No single canonical reliability dashboard with hard gate pass/fail and provenance.

**No-BS verdict:** observability is rich but not yet authoritative.

---

## 4) Regressions / Risk Ledger (things easy to underweight)

1. **Noise burden breach persists (0.758 > 0.65)**
   - Impact: advisory fatigue, operator distrust, hidden false positives.

2. **Mind/offline queue debt (14k+)**
   - Impact: delayed learning sync; stale context; recovery complexity.

3. **Trace coverage collapse (10% strict)**
   - Impact: strategic decisions based on weak attribution.

4. **Advisory packet freshness/readiness at zero**
   - Impact: recommendations may be technically “effective” but operationally stale.

5. **Watchdog inactive**
   - Impact: silent degraded mode risk during unattended windows.

6. **Metric incoherence across surfaces**
   - Impact: leaders can optimize the wrong bottleneck.

---

## 5) Onboarding Deep-Dive (critical priority)

## 5.1 Current onboarding doc quality
`docs/SPARK_ONBOARDING_COMPLETE.md` is well-structured and comprehensive.  
Problem is likely **operational onboarding**, not document length.

### Core onboarding failure modes likely happening
1. **Too many moving services at first-run** (sparkd/bridge/watchdog/pulse/mind/hooks) without progressive mode.
2. **Hooks merge step requires manual JSON surgery** (`~/.claude/settings.json`), error-prone.
3. **Success criteria ambiguity**: users can pass initial checks but still have non-functional advice flow later.
4. **No onboarding confidence score** shown to user (“you are 63% correctly configured”).
5. **LLM strategy not integrated into first-run path**: provider/cost/latency expectations come late.

## 5.2 Onboarding redesign proposal (practical)

### Phase A — Progressive first-run modes
- **Mode 1: Local-safe baseline** (no external LLM, minimal services, guaranteed simple success)
- **Mode 2: Guided LLM mode** (provider choice + budget/latency presets)
- **Mode 3: Full architecture mode** (watchdog + pulse + observatory + advanced tuning)

### Phase B — Deterministic verification checkpoints
Introduce a single command:
- `spark onboard verify --strict`

Output should include:
- hooks firing ✅/❌
- advisory emit path live ✅/❌
- packet freshness ✅/❌
- mind sync lag class (green/yellow/red)
- watchdog state ✅/❌
- final onboarding score (0–100)

### Phase C — Auto-remediation for common errors
- JSON hook merge guard/patch assistant
- stale lock auto-repair
- one-click “safe reset but keep memories” command

---

## 6) Strategic LLM Integration Plan (User-selectable by subsystem)

Your request (cheap models like MiniMax/Kimi for specific lanes) is exactly the right direction.

## 6.1 Current status
- Existing docs and code already support multi-provider direction (`docs/MINIMAX_INTEGRATION.md`, config authority mappings).
- There is active setup work in repo (`scripts/intelligence_llm_setup.py`, `lib/intelligence_llm_preferences.py`) that can become official onboarding UX.

## 6.2 What to productize now
Build **LLM Usage Matrix** inside onboarding and tuneables UI:

| Subsystem | Default | User-selectable options | Why this split matters |
|---|---|---|---|
| Advisory synthesis | local/auto | ollama/minimax/kimi/openai/anthropic | latency + quality tradeoff |
| EIDOS distillation refinement | off/auto | same | quality uplift but not always needed |
| Meta-Ralph NEEDS_WORK refinement | off/auto | same | salvage borderline insights cheaply |
| Opportunity scanner | conservative | same | avoid expensive constant scanning |
| Packet rerank LLM | off by default | same | high latency/cost, opt-in |

## 6.3 Required policy controls (must-have)
1. **Per-lane token/cost budgets** (daily/weekly caps)
2. **Timeout by lane** (hard fail-fast)
3. **Fallback hierarchy** (cheap-first policy optional)
4. **Privacy class per lane** (what data each provider can see)
5. **Outcome quality tracker by provider** (not just call success)

## 6.4 Kimi + MiniMax practical policy
- Use MiniMax/Kimi for: distillation, opportunity scanning, low-risk synthesis
- Keep high-stakes decision layers with stricter/local options unless confidence is proven
- Add quality leaderboard: `provider × lane × outcome effectiveness`

---

## 7) Blind Spots We’re Not Paying Enough Attention To

1. **Cross-surface metric contracts**
   - Need one source-of-truth schema so queue/backlog metrics cannot disagree silently.

2. **Staleness semantics**
   - “system up” is not equal to “system useful”; freshness SLAs need to be first-class.

3. **Operator cognitive load**
   - Tons of docs and dashboards exist, but triage path is still heavy during incidents.

4. **False confidence from partial pass rates**
   - High effectiveness in one slice can mask catastrophic strict linkage failure.

5. **Onboarding to value-time**
   - Need measured “time-to-first-useful-advice” as a core north-star metric.

---

## 8) Priority Action Plan (Next 14 Days)

## P0 (Days 1–3)
1. **Unify queue truth model** (event/pending/offline sync) + expose one canonical metric panel.
2. **Restore watchdog operation** and wire alert when down > 2 cycles.
3. **Ship strict trace linkage patch** to push strict coverage from 10% → 35% minimum.

## P1 (Days 4–7)
4. **Advisory packet freshness fix** (TTL + invalidation + key stability).
5. **Noise-burden reduction sprint** targeting <0.65 and sustained.
6. **Onboarding verify command** with pass/fail score.

## P2 (Days 8–14)
7. **Onboarding LLM lane selector** (integrate existing setup script into onboarding).
8. **Per-lane budget + privacy classes**.
9. **Provider-lane quality leaderboard** in observatory/pulse.

---

## 9) Suggested KPIs (No-BS Dashboard)

Must show daily, with red gates:
- noise_burden (target <=0.65)
- strict_trace_coverage (target >=0.50)
- strict_acted_on_rate (target >=0.20)
- advisory_packet_freshness (target >=0.35)
- offline_queue_depth (target <=2000)
- watchdog_uptime (target >=99%)
- time_to_first_useful_advice_onboarding (target <=20 min)
- onboarding_success_rate_1st_try (target >=85%)

---

## 10) Final Bottom Line

You are absolutely progressing — but the key blockers are now **system coherence and operational trust**, not feature count.

If we fix only three things first:
1) trace linkage,  
2) queue/sync debt + metric coherence,  
3) onboarding reliability + LLM lane configuration UX,  
then Spark Intelligence moves from promising to genuinely scalable.

Until those are fixed, claims of readiness should stay conservative.

---

## Appendix A — Key Inputs used
- `scripts/carmack_kpi_scorecard.py --window-hours 24 --alert-json`
- `scripts/carmack_kpi_scorecard.py --window-hours 168 --alert-json`
- `python cli.py status`
- `python scripts/production_loop_report.py`
- `_observatory/.observatory_snapshot.json`
- `_observatory/changes_since_last_regen.md`
- `docs/SPARK_ONBOARDING_COMPLETE.md`
- `docs/LLM_INTEGRATION.md`
- `docs/MINIMAX_INTEGRATION.md`
- `scripts/intelligence_llm_setup.py` (active setup flow)
- `lib/intelligence_llm_preferences.py` (runtime preference persistence)
