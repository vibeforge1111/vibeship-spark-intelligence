# Governance: Promoter

> **File**: `lib/promoter.py`
> **Role**: Promotes high-reliability insights to user-facing project files (CLAUDE.md, AGENTS.md, TOOLS.md, SOUL.md).

## Identity

**IS**: The final filter before intelligence becomes permanent user-facing guidance. Only the most validated, reliable, and actionable insights should reach this stage.

**IS NOT**: An aggregator or summarizer. It promotes individual insights verbatim (with formatting). Not a discovery engine — it acts on what's already stored and validated.

## Hard Rules

| Rule | Source Lesson | Why |
|------|--------------|-----|
| Minimum 5 validations required for Track 1 | L21: Promote only evidence-backed | Single validation is anecdotal; 5 is a pattern |
| Minimum 80% reliability required | L15: Reliability needs contradiction pressure | Below 80%, contradiction evidence is too strong |
| Fast-track requires 95% confidence AND 6h age | L18: Small testable proof | High confidence without time-testing is premature |
| Operational patterns NEVER promoted | L1: Raw telemetry ≠ intelligence | Tool sequences, usage counts, and benchmark artifacts are not user guidance |
| File budgets enforced (CLAUDE.md: 40, AGENTS.md: 30) | L14: Keepability > volume | Unbounded promotion creates unreadable files |
| Demoted insights don't auto-remove from files | L19: Reversible-step thinking | Requires explicit clean-up to prevent accidental deletion of manually-added content |

## Anti-Patterns

| Pattern | Why It's Bad | Detection |
|---------|-------------|-----------|
| Promoting insights with only validation count, no contradiction check | 5 validations + 4 contradictions = still unreliable | times_contradicted >= times_validated / 2 |
| Promoting vague insights because they're old and validated | "Always write good code" validated 10 times is still useless | Promoted text fails the "would a human find this useful?" test |
| Promoting without checking current file content | Creates duplicates in CLAUDE.md | Same insight text appearing multiple times in target file |
| Batch-promoting everything at once | User sees 15 new lines in CLAUDE.md and doesn't trust any of them | >5 promotions in a single cycle |
| Not tracking demotion reasons | We demote but don't know why — same pattern may get re-promoted | Demotion log missing reason field |

## Socratic Questions

1. **Do promoted insights actually change behavior?** If CLAUDE.md says "Always validate auth tokens" — does Claude actually validate auth tokens more often? Or is the promoted text ignored?

2. **Are we promoting the right LEVEL of insight?** "Never commit secrets" is too obvious. "Use PKCE for OAuth in SPAs" is actionable but narrow. What level of specificity makes a promotion useful?

3. **Is the 6-hour settling period enough for fast-track?** An insight that looks brilliant for 6 hours might be wrong. Should fast-track require 24 hours? Or is 6 hours fine because we have demotion?

4. **What's in CLAUDE.md RIGHT NOW that shouldn't be?** When was the last audit? Are there promoted insights that have since been contradicted but weren't demoted?

5. **Should promotions decay?** An insight promoted 3 months ago about a deprecated API version is now harmful. Should promoted insights have TTL?

## Success Metrics

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Promotion rate | 1-3 insights per week | Track promotion_log.jsonl growth |
| Promoted insight relevance | >80% useful when reviewed | Monthly audit of CLAUDE.md Spark section |
| Demotion rate | <10% of promoted insights demoted | Track demotion events |
| File budget utilization | 50-80% of budget used | Count lines in Spark sections |
| Stale promotion rate | <5% of promoted insights >90 days without validation | Age analysis of promoted insights |

## Failure Signals

- >10 promotions per day → quality gate too lenient or validation inflation
- 0 promotions per month → pipeline not producing promotable insights
- CLAUDE.md Spark section >40 lines → budget overflow or no pruning
- Same insight promoted and demoted repeatedly → threshold oscillation
- User manually deleting promoted insights → trust issue with promotion quality

## Lesson Map

| Lesson | Application |
|--------|------------|
| L1 (telemetry ≠ intelligence) | Operational pattern filter blocks telemetry promotion |
| L14 (keepability > volume) | File budgets enforce quality over quantity |
| L15 (contradiction pressure) | 80% reliability threshold includes contradiction weighting |
| L19 (reversible steps) | Demotion doesn't auto-remove from files |
| L21 (evidence-backed only) | 5 validations minimum for Track 1 |
