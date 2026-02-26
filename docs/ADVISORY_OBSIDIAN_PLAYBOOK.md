# Obsidian Watchtower Playbook

Use this for best-practice observability use of advisory packets.

## What you get in the watchtower

Spark exports three notes into:

- `<obsidian_export_dir>\packets\index.md`
- `<obsidian_export_dir>\watchtower.md`
- `<obsidian_export_dir>\packets\<packet_id>.md` (raw `packet_id`, not `pkt_` prefix)

The watchtower is for:
- quickly seeing what is currently ready vs stale/inactive
- tracking suppression and outcome context
- choosing which packets to promote into your working memory or SOPs

## Recommended folder structure

- Keep the packets folder at a stable location, e.g.
  - `<YOUR_OBSIDIAN_VAULT>/Spark-Intelligence-Observatory`
- In Obsidian, create a pinned note tab for:
  - `Spark\Watchtower\watchtower.md`
  - `Spark\Watchtower\packets\index.md`
- Optional: create a quick note `Spark Watchtower Log` and copy high-value packets there.

## Daily "quick read" flow (5 minutes)

1. Open `watchtower.md`.
2. Check header counters:
  - `ready`, `stale`, `invalidated`, `entries`
3. Check the **Top ready packets** section.
4. Open `packets\index.md` for exact packet bodies and context.
5. In watchtower header, check `trace health` to see required-system score at a glance.
6. Review up to one **Ready Packet** in-session:
   - pick one packet you can apply this session.
7. Open packet and decide one action:
   - **Use now**: execute it in your workflow.
   - **Archive**: mark mentally for review.
   - **Ignore**: if unrelated context; no action needed.
8. If this packet still feels unclear, open `packets\<packet_id>.md` and read in this fixed order:
   - `Packet story for humans`
   - `Here are the memories`
   - `Here are the distilled versions`
   - `Here are transformed ones`
   - `Here is how they got transformed`
   - `What Meta-Ralph said`
   - `What is ready for advisory`
   - `What is getting pulled as advisory`
   - `What may need work`

## Weekly review flow (20–30 minutes)

1. Open `watchtower.md` and review suppression trends.
2. Open `packets\index.md` and scan `Packet catalog snapshot`.
2. For stale packets with high effect scores, decide if context changed or they still belong:
   - same root advice: consolidate and pin a single evergreen entry
   - contradictory advice: keep both as alternatives and add a decision note
3. If you see repeated invalidation reasons (same reason many times), treat that as
   a pipeline smell and open a maintenance task.
4. Create/refresh a short weekly note:
   - `## Spark Watchtower Weekly`
   - include top 3 packets you actually acted on
   - include 1 missed opportunity and 1 false positive

## How to use packet pages efficiently

Each packet page gives you:
- creation/update timing
- project and tool context
- source and category tags
- readiness and freshness signals
- invalidation reason if applicable
- advisory text and actionability details
- a readable pipeline walk-through:
  - memories -> distilled -> transformed
  - transformation and pull history
  - what is ready now and what still needs work

Use this pattern:
- click a candidate packet from index
- read only the top metadata + advisory text
- check these sections in order:
  - `Packet story for humans`
  - `Here are the memories`
  - `Here are the distilled versions`
  - `Here are transformed ones`
  - `Here is how they got transformed`
  - `What Meta-Ralph said`
   - `What is ready for advisory`
   - `What is getting pulled as advisory`
   - `Advisory Traceability Timeline` (then `Trace-system coverage`)
     - verify trace IDs are present for this packet
     - `ok` means at least one row from that system was seen in this packet context
     - optional systems (`advisory_outcome`, `outcome_links`, `implicit_feedback`) can appear as data arrives
   - `What may need work`
9. Open `watchtower.md` and check:
  - `Trace health pane (global, last N cycles)` for required/optional system activity and missing systems.
  - `Trace-system heatmap (sample of recent packets)` for packet-level trace coverage.
- either:
  - apply in current task immediately, or
  - defer and add a quick backlink in your task note

## Best-practice conventions

- Treat `index.md` as the operational dashboard, not a filing cabinet.
- Treat per-packet notes as trace evidence for decisions.
- Keep decisions close to work:
  - if a packet changes behavior, add a short note in your task note with packet link
  - if a packet is repeatedly ignored, leave it for observation only
- Do not over-index on stale packets.
  - Freshness window and readiness are intentional; prioritize `Ready` section.

## Safe operating limits (important)

- This is an observation tower, not a hard source of truth.
- Never auto-apply every ready packet blindly.
- If your workflow gets noisy, reduce:
  - `advisory_gate.max_emit_per_call`
  - or increase `advisory_gate.advice_repeat_cooldown_s` in tuneables

## One-line refresh checklist

Run after path/tuneable changes:

```bash
python scripts/set_obsidian_watchtower.py --show
python scripts/set_obsidian_watchtower.py --show # (confirm path + enabled)
```

Then run a normal advisory session to trigger real packet writes.

## One-command watchtower health check

```bash
python scripts/check_obsidian_watchtower.py
```

- This checks:
  - obsidian config + enabled flags
  - export directory state
  - sync execution (`_sync_obsidian_catalog`)
  - presence of `index.md` + `watchtower.md`

## Troubleshooting

- No `index.md`: confirm Spark process loaded updated tuneables and restart.
- Missing packet list: exports are blocked or disabled (check `obsidian_enabled` and `obsidian_auto_export`).
- Wrong folder: verify `obsidian_export_dir` points at the vault path used by Obsidian.
- Noisy output: temporarily disable auto export, inspect pipeline behavior, re-enable once cleaned.
