# Spark CLI System Blueprint

Status: proposed (implementation guide)  
Last updated: 2026-02-24  
Owner: Spark runtime/UX

## 1) Why this document exists

Spark already has deep capabilities in `spark/cli.py` (runtime control, learning, advisory, outcomes, project intelligence, chips).  
The gap is onboarding clarity and operational ergonomics for first-time and everyday users.

This document defines the CLI ruleset, product intent, and rollout plan for a "one-command to first value" experience while preserving Spark's advanced power.

## 2) Product intent the CLI must serve

Spark is a local intelligence runtime, not a chatbot shell. The CLI must help users move through this loop with minimal friction:

`capture -> distill -> transform -> advise -> act -> outcome feedback -> improved advice`

Non-negotiable product constraints:
- Local-first behavior by default.
- Deterministic, scriptable operations for advanced users.
- Safety and reversibility for config/repair actions.
- Fast path for beginners without hiding power features.

## 3) Problems this CLI system solves

### First-time user problems
- "I installed it, now what?"
- "Which command should I run first?"
- "How do I know it is actually working?"
- "How do I connect my agent hooks without breaking my setup?"

### Returning/power user problems
- "I need one command to bring everything up and confirm health."
- "I need machine-readable output for scripts/CI."
- "I need a diagnosis command that can fix common issues safely."
- "I need consistent command and flag behavior across all subcommands."

### Team/operator problems
- "We need one canonical onboarding flow for docs, web page, and terminal."
- "We need stable exit codes and JSON schema for automation."
- "We need objective CLI success metrics (time-to-first-value)."

## 4) External CLI patterns worth adopting

From OpenClaw, Claude Code, Aider, and Gemini CLI:

- OpenClaw: clear lifecycle commands (`setup`, `onboard`, `doctor`, `status`, `health`, `logs`, `config get/set/unset`) and strong repair semantics (`--repair`, non-interactive behavior, backup before mutation).
- Claude Code: strong health/status primitives (`/doctor`, `/status`, `/config`, `/memory`) and explicit headless/script modes (`-p`, `--output-format json`, session resume).
- Aider: tight "fix loop" primitives (`/lint`, `/test`, `/undo`, `/reset`) and rich command-line options for lint/test/autofix and approval behavior.
- Gemini CLI: explicit automation contract (`--prompt`, stdin, JSON output, stable exit codes) plus memory/session primitives (`/memory`, `/chat save/resume/list`).

These patterns align with Spark's needs and should be adapted to Spark terminology and architecture.

## 5) What "perfect CLI for Spark" means

A perfect Spark CLI is:
- Beginner-safe: first success in minutes with guided verification.
- Operator-grade: deterministic output, clear exit codes, no guesswork.
- Architecture-aware: commands map directly to Spark subsystems (services, hooks, queue, advisory, context sync, quality gates).
- Recoverable: failures always provide next action and optional auto-repair.
- Sticky: users keep using CLI after install because it helps daily workflow, not just setup.

## 6) CLI ruleset (canonical behavior contract)

Use MUST/SHOULD semantics as implementation requirements.

### 6.1 Command model
- MUST keep one root command namespace: `spark <command>`.
- MUST keep advanced commands; do not remove existing depth.
- MUST add a beginner lifecycle layer on top:
  - `spark onboard`
  - `spark doctor`
  - `spark run` (one-command start+verify wrapper)
  - `spark logs`
  - `spark config`

### 6.2 Global flags
- MUST support `--json` on all user-facing diagnostic/lifecycle commands.
- MUST support `--profile <name>` to isolate runtime state (similar to OpenClaw profile isolation).
- SHOULD support `--no-color` and honor `NO_COLOR=1`.
- SHOULD support `--non-interactive` for commands that normally prompt.
- SHOULD support `--yes` for mutating commands that can run unattended.

### 6.3 Output contract
- Human mode MUST use compact sections: `Status`, `Findings`, `Actions`.
- JSON mode MUST return structured objects with:
  - `ok` (bool)
  - `command`
  - `checks[]` (`id`, `status`, `message`, `details`)
  - `actions[]` (`label`, `command`, `safe`)
  - `errors[]` (if any)
- MUST avoid mixed machine/human output in `--json` mode.

### 6.4 Exit code contract
- `0`: success / healthy
- `1`: command completed but checks failed (action required)
- `2`: usage/validation error
- `3`: partial success (some repairs applied, rerun needed)
- `>=10`: unexpected internal failure

### 6.5 Safety and repair
- Mutating repair commands MUST create backups before changing config/state.
- Repair commands MUST print exactly what changed.
- Interactive prompts MUST be skipped in non-TTY or `--non-interactive` mode.
- Destructive operations MUST require explicit confirmation (`--yes`).

### 6.6 Config semantics
- `spark config` MUST support: `get`, `set`, `unset`, `validate`, `diff`.
- Paths SHOULD support dot/bracket notation (for consistency with OpenClaw familiarity).
- Values SHOULD support strict typed parsing mode plus plain-string fallback.
- Config precedence MUST remain aligned with `docs/CONFIG_AUTHORITY.md`.

### 6.7 Discoverability
- `spark --help` MUST show beginner-first "start here" commands before advanced commands.
- Each command MUST include at least 3 examples.
- Errors MUST include one exact recovery command whenever possible.

## 7) Command architecture for Spark

## 7.1 Keep current command families
- Runtime: `up`, `ensure`, `down`, `status`, `services`, `health`, `events`
- Learning/advisory: `learnings`, `promote`, `advisory`, `outcome*`, `advice-feedback`
- Intelligence systems: `eidos`, `project`, `chips`, `opportunities`
- Context/memory: `sync-context`, `sync`, `memory`, `sync-banks`

## 7.2 Add/standardize lifecycle families

### `spark onboard`
Purpose: first-time and re-onboarding wizard.

Modes:
- `spark onboard` (interactive)
- `spark onboard --quick --yes` (non-interactive fast path)
- `spark onboard --agent claude|cursor|openclaw|codex`
- `spark onboard status|resume|reset`

Core steps:
1. Preflight (python/pip/git/ports/path)
2. Service bootstrap (`spark up`)
3. Health verification (`spark health`, `spark services`)
4. Agent connection checks (hooks/tasks/tailer)
5. First learning proof (`spark events`, minimal advisory readiness check)
6. Next steps tailored to user agent choice

State:
- Store progress at `~/.spark/onboarding_state.json`

### `spark doctor`
Purpose: diagnosis + optional safe repair.

Modes:
- `spark doctor`
- `spark doctor --deep`
- `spark doctor --repair` (alias `--fix`)
- `spark doctor --json --non-interactive`

Check categories:
- Install/runtime environment
- Service/process health
- Hook ingestion and recent event flow
- Queue/bridge health
- Advisory readiness path
- Mind/pulse optional dependencies
- Config integrity + drift + schema validation

### `spark run`
Purpose: one command for "I just want Spark working now."

Behavior:
- Equivalent to `up -> health -> services -> optional sync-context`
- Supports `--lite`, `--project`, `--sync-context`, `--json`

### `spark logs`
Purpose: standard logs access for local operators.

Behavior:
- `spark logs --service sparkd|bridge_worker|mind|pulse|watchdog`
- `spark logs --follow`
- `spark logs --since 1h`
- `spark logs --json`

### `spark config`
Purpose: portable config management for humans and automation.

Behavior:
- `spark config get <path>`
- `spark config set <path> <value>`
- `spark config unset <path>`
- `spark config validate`
- `spark config diff` (runtime vs baseline)

## 8) First-time user priority system

The CLI must optimize for "time to first confidence", not only install completion.

Definition of first confidence:
1. Services are running.
2. Health passes.
3. At least one event can be seen.
4. User knows next 2 commands to continue value.

Required onboarding UX decisions:
- Use checklists with visible progress.
- Always print "what happened" and "what to do next."
- Never end onboarding on a silent success.
- Surface a one-line summary for non-technical users and a detailed view for operators.

## 9) Bug-fix and self-healing model

The CLI should treat failures as diagnosable states, not dead ends.

Required bug-fix loop:
1. Detect (`spark doctor`)
2. Explain root cause in plain language
3. Offer exact repair command
4. Apply safe repair (optional)
5. Re-verify automatically
6. Emit status + next action

Repair principles:
- Prefer minimally invasive fixes.
- Snapshot files before edits.
- Keep repair logs in `~/.spark/logs/doctor/`.

## 10) Complementary systems that must connect to CLI

CLI is the center, but not the only surface.

Required connected surfaces:
- Install scripts (`install.ps1`, `install.sh`) should invoke `spark onboard --quick --yes`.
- Onboarding web page should call the exact same step definitions as CLI.
- Spark Pulse should show onboarding/health card using CLI-compatible check IDs.
- Docs (`GETTING_STARTED_5_MIN`, `QUICKSTART`, `SPARK_ONBOARDING_COMPLETE`) should reference lifecycle commands consistently.
- Agent integration scripts should be callable from onboarding steps.

Single-source requirement:
- Step definitions must live in one canonical data model reused by CLI, docs rendering, and web UI.

## 11) Aha and wow moments to design intentionally

These are not gimmicks. They are proof moments that create trust.

### Aha moments (first session)
- "First green path": `spark onboard` shows all critical checks green in one screen.
- "First evidence": `spark onboard` shows first captured event count.
- "First intelligence proof": quick explanation of one surfaced learning/advice path.

### Wow moments (ongoing usage)
- "What changed since yesterday": `spark status --delta 24h` summary.
- "Advice health clarity": `spark doctor --deep` can explain why advice is suppressed.
- "Project context intelligence": `spark project status` integrated into onboarding follow-up.
- "One command confidence": `spark run` for daily startup without remembering internals.

### Retention moments
- Weekly digest command (`spark recap --days 7`) can show:
  - most reliable learnings
  - acted vs ignored advisories
  - top recurring failures and suggested fixes

## 12) Metrics and success criteria

Primary UX metrics:
- Time to first healthy runtime (TTHR)
- Time to first captured event (TTFE)
- Time to first advisory-ready state (TTFA)
- Onboarding completion rate
- Doctor success rate without manual intervention
- Daily active CLI lifecycle usage (`run`, `status`, `doctor`, `logs`)

Quality guard metrics:
- Repair-induced regression rate
- False-positive doctor findings
- Command error rate by subcommand

## 13) Phased implementation plan

### Phase 1 (foundation)
- Implement `spark onboard` (interactive + quick + status/resume/reset)
- Implement `spark doctor` (checks + JSON + non-interactive)
- Add global `--json` + exit code standard to lifecycle commands

### Phase 2 (operator ergonomics)
- Implement `spark logs`
- Implement `spark config get/set/unset/validate/diff`
- Add `spark run` wrapper

### Phase 3 (connected UX)
- Connect install scripts to onboarding
- Add onboarding card in Pulse
- Add unified step schema for docs/web/CLI

### Phase 4 (delight and retention)
- Add recap/delta style commands
- Add richer advisory explainability in doctor/status outputs

## 14) Acceptance checklist for "Spark CLI 1.0 UX"

- A first-time user can go from no setup to healthy runtime with one command.
- A failed setup can be diagnosed and repaired with one command.
- Every key lifecycle command supports JSON and stable exit codes.
- Docs, web onboarding, and CLI steps are synchronized from one source.
- Advanced users retain full control of existing Spark command depth.

## 15) External references used

- OpenClaw CLI reference and command pages (`setup`, `onboard`, `doctor`, `status`, `health`, `logs`, `config`):
  - https://docs.openclaw.ai/cli/index
  - https://docs.openclaw.ai/cli/setup
  - https://docs.openclaw.ai/cli/onboard
  - https://docs.openclaw.ai/cli/doctor
  - https://docs.openclaw.ai/cli/status
  - https://docs.openclaw.ai/cli/health
  - https://docs.openclaw.ai/cli/logs
  - https://docs.openclaw.ai/cli/config
- Claude Code docs:
  - Interactive commands (`/doctor`, `/config`, `/status`, `/memory`, `/mcp`): https://code.claude.com/docs/en/interactive-mode
  - CLI flags and structured output (`-p`, `--output-format json`, automation/session flags): https://code.claude.com/docs/en/cli-reference
- Aider docs:
  - In-chat command ergonomics (`/lint`, `/test`, `/undo`, `/drop`, `/reset`, `/run`): https://aider.chat/docs/usage/commands.html
  - Option depth (`--lint-cmd`, `--test-cmd`, `--watch-files`, `--yes-always`): https://aider.chat/docs/config/options.html
  - Lint/test repair loop philosophy: https://aider.chat/docs/usage/lint-test.html
- Gemini CLI docs:
  - Slash/at/exclamation command model, tool discovery, memory/session commands: https://google-gemini.github.io/gemini-cli/docs/cli/commands.html
  - Headless automation (`--prompt`, stdin, `--output-format json`, scripting patterns): https://google-gemini.github.io/gemini-cli/docs/cli/headless.html
  - Memory persistence model (`save_memory`): https://google-gemini.github.io/gemini-cli/docs/tools/memory.html
