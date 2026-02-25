# Memory Observability Stack

## Active observatories

1. **Daily Memory Quality Observatory**
   - Script: `scripts/memory_quality_observatory.py`
   - Snapshot: `_observatory/memory_quality_snapshot.json`
   - Report: `docs/reports/<date>_memory_quality_observatory.md`

2. **No-BS Daily Scorecard (23:00 Dubai)**
   - Includes memory observatory findings in daily executive report.

## Core metrics

- `capture.noise_like_ratio` (target: < 0.20)
- `context.p50` (target: >= 120 chars)
- `semantic_retrieval.sim_lt_0_1_ratio` (target: < 0.15)
- `advisory_engine.global_dedupe_ratio` (target: < 0.45)
- `missed_capture.missed_high_signal / candidate_high_signal` (target: < 0.25)

## Next observatories to add

- Top-noise signature leaderboard (source+phrase+count)
- Missed high-signal taxonomy (decision/preference/constraint/causal)
- Memory utility outcome linkage (which memory actually improved outcomes)

## Run manually

```bash
python scripts/memory_quality_observatory.py
```
