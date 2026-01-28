# Spark ↔ Clawdbot Memory Contract (File-Based)

This document defines a **single, explicit contract** between Spark (events → learnings) and Clawdbot (constitution + memory files).

Goal: keep Clawdbot **fast + low-context by default**, while Spark does the heavy lifting of capture/distillation—*without* creating competing memory stores.

## Canonical sources of truth

Clawdbot is file-first. These are the canonical, human-readable sources:

- **Constitution (stable, high-trust):**
  - `SOUL.md` — assistant identity/voice/boundaries
  - `USER.md` — user profile + preferences
  - `AGENTS.md` — runtime/operating rules for the workspace
- **Memory (two-tier):**
  - `memory/YYYY-MM-DD.md` — daily log (raw, chronological)
  - `MEMORY.md` — long-term curated memory (durable facts, preferences, ongoing projects)

Spark should treat these as the "truth".

## Spark’s role

Spark is the automation layer:

1) Capture high-volume events into Spark’s own store (queue, insights).
2) Distill patterns into **proposals**.
3) Propose edits to Clawdbot files via **patches** (reviewable), not silent rewrites.

## Ownership model (who may write what)

### Spark MAY
- Create **patch proposals** for:
  - `MEMORY.md` (long-term additions)
  - `memory/YYYY-MM-DD.md` (daily digests/sections)
  - *optionally* `USER.md` (only high-confidence, repeated preferences)
- Write to Spark-owned artifacts:
  - `SPARK_CONTEXT.md`
  - Spark bank files under `~/.spark/**`

### Spark MUST NOT (by default)
- Rewrite/reshape `SOUL.md` or `AGENTS.md` automatically.
- Directly edit `MEMORY.md` unless explicitly run with an `--apply` flag.

## Metadata required for promotions

Every proposed memory item should include:

- **scope:** `global` | `project`
- **share_scope:**
  - `main_only` (never safe to surface outside main session)
  - `safe_general` (safe across contexts)
- **sensitivity:** `low` | `medium` | `high`
- **category:** existing Spark category (`user_understanding`, `communication`, etc.)

Why: Clawdbot’s security boundary ("only load MEMORY.md in main session") is good—Spark should strengthen it, not weaken it.

## Promotion pipeline (single contract)

1) **Capture** (Spark queue): everything goes here.
2) **Daily digest** (`memory/YYYY-MM-DD.md`): Spark can propose/append a small section:
   - Decisions
   - Preferences observed
   - Lessons learned
3) **Long-term memory** (`MEMORY.md`): only durable items.

Spark should default to creating a **patch proposal** for step (3).

## Conflict + duplication handling

Before proposing a new line in `MEMORY.md`, Spark should:

- Skip if the exact insight already exists.
- Flag potential conflicts when the same "topic" appears with a different preference.
  - Heuristic: if an insight contains `topic: preference` then treat the text before `:` as a topic key.

Conflicts should be surfaced as:
- a separate proposal note, or
- a patch that adds under a "⚠ Conflicts to review" subsection.

## Review workflow

Spark generates patches into:

- `<workspace>/.spark/proposals/*.patch`

Human reviews (or a Clawdbot run applies).

Apply is explicit:
- `spark bridge --promote --apply`

Default is safe:
- `spark bridge --promote` (proposal only)

## Practical defaults

- Use "propose, don’t apply" as the default.
- Keep constitution files stable.
- Prefer small, additive patches.

---

If you change this contract, update this doc first.
