# Spark Intelligence — No-BS Scorecard (Template)

Use this for daily/weekly reporting. If a gate fails, mark it red. No soft wording.

## 0) Report Meta
- Generated at (Asia/Dubai):
- Window: last 24h / 7d
- Analyst mode: no-BS

---

## 1) Hard Gates (Red if any fail)
| Gate | Target | Current | Status | Evidence |
|---|---:|---:|---|---|
| Noise burden | <= 0.65 |  |  | `scripts/carmack_kpi_scorecard.py` |
| Bridge heartbeat age | <= 120s |  |  | heartbeat file / scorecard |
| Core reliability | >= 0.75 |  |  | scorecard |
| GAUR | >= 0.20 |  |  | scorecard |
| Queue depth | <= 2000 |  |  | `spark status` / queue metrics |
| Trace linkage quality | improving trend |  |  | advisory self review |

**Gate verdict:** GREEN / YELLOW / RED

---

## 2) Stability (Truth)
- What improved (proof-based):
- What regressed (proof-based):
- Most likely failure mode if unchanged:

## 3) Scalability (Truth)
- Throughput/queue pressure signals:
- Backlog debt (Mind/offline queue):
- Hotspots under sustained load:

## 4) UX + Operability (Truth)
- Operator friction points:
- Onboarding/CLI/documentation reality check:
- User-visible weirdness/noise:

## 5) Architecture Health (Truth)
- Strong zones (modules/flows):
- Fragile zones (coupling/dual paths/complexity tax):
- Where architecture is lying to us (design says X, runtime says Y):

## 6) Observability + Watchtower Coverage
- Pulse status:
- Observatory freshness:
- Missing watchtowers (blind spots):
- Alert quality (signal vs noise):

## 7) Security + Safety
- New hardening landed:
- Current exposure risks:
- Required immediate fixes:

## 8) Regressions Ledger (No excuse section)
| Regression | First seen | Impact | Owner | ETA | State |
|---|---|---|---|---|---|

## 9) Top 5 Next Actions (ranked by impact/speed)
1.
2.
3.
4.
5.

## 10) Brutal Bottom Line
- What is actually true right now:
- What we should stop pretending is fine:
- Release posture: NOT READY / LIMITED READY / READY

## 11) Triple Self-Interrogation (Mandatory)
- Run 10–12 fresh Q&A each for:
  1) Memory quality/capture
  2) Advisory emissions/suppression
  3) Website UX + onboarding flow
- Use: `docs/reports/SELF_INTERROGATION_TRIPLE_TEMPLATE.md`

---

## Data Pull Commands (reference)
```bash
python scripts/carmack_kpi_scorecard.py --window-hours 24 --alert-json
python cli.py status
python scripts/production_loop_report.py
```

Self-review references:
- `docs/reports/*_advisory_self_review.md`
- latest `reports/spark_tracker_snapshot.md`
- latest `reports/spark_change_effects.md`
