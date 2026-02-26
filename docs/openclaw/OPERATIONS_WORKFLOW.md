# OpenClaw Integration Operations Workflow

This workflow keeps Spark x OpenClaw changes organized and auditable in git.

## Commit strategy

Use one concern per commit and push each commit immediately:

1. `docs(...)` commit for intent/spec/backlog updates.
2. `fix(...)` or `feat(...)` commit for code/config tooling.
3. `docs(reports)` commit for post-change audit evidence.

Do not batch unrelated changes into one commit.

## Recommended loop

1. Update backlog and changelog
- `docs/openclaw/INTEGRATION_BACKLOG.md`
- `docs/openclaw/INTEGRATION_CHANGELOG.md`

2. Implement one change
- Keep scope minimal and testable.

3. Validate
- Run targeted tests for touched areas.
- Run audit:
  - `python scripts/openclaw_integration_audit.py`
- Run strict-quality lineage rollup:
  - `python scripts/openclaw_strict_quality_rollup.py --window-days 7`
- Run realtime benchmark (live canary + strict loop checks):
  - `python scripts/openclaw_realtime_e2e_benchmark.py --window-minutes 90 --run-canary --canary-agent spark-speed`
- Prompt template for running the same benchmark from OpenClaw:
  - `docs/openclaw/REALTIME_E2E_PROMPT.md`

4. Commit and push
- Use explicit messages with scope:
  - `docs(openclaw): ...`
  - `fix(health): ...`
  - `feat(audit): ...`

5. Save report artifact
- Commit generated report files from `docs/reports/openclaw/`.

## Minimum evidence per integration change

- What changed (1-3 lines)
- Why it changed
- How it was validated
- Residual risk and next action
