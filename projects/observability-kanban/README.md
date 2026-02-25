# Observability Kanban Project

A reusable execution dashboard for Spark Intelligence initiatives, redesigned with a vibeship.co plus terminal-inspired visual system.

## Purpose
Turn analysis and questions into measurable execution:
- Task intent and goal per card
- KPI baseline and target linkage
- Column-based Kanban flow with guardrails
- Daily and weekly analytics on movement and impact

## Features
- Responsive mobile and desktop hierarchy
- KPI cards with compact baseline/target progress bars
- KPI trend mini-charts (from `data/kpi_history.json`)
- Kanban columns with drag-and-drop movement
- In-card move selector for touch and mobile workflows
- WIP limits with over-limit warning states
- Card aging (days in current column)
- Effect-check workflow before moving KPI tasks to `DONE`
- Auto-routing to `NEEDS_REVIEW` after repeated failed effect checks (default threshold: 2)
- Checklist modal required when moving `NEEDS_REVIEW` back to `READY`
- Per-card compact history timeline (moves, effect checks, review checklist events)
- Local persistence (board state saved in browser)
- Question-derived backlog (actionable tasks from interrogation questions)
- Analytics summary (task counts, average priority, top next tasks)
- Export current board state to JSON

## UI refresh notes
- Modern minimal card layout with stronger information hierarchy
- Cleaner column headers with count plus WIP metadata
- Compact metric chips for priority, impact, urgency, risk, effort, score, and status
- Terminal accents via mono labels and lightweight scanline texture
- Improved spacing, contrast, and focus states for accessibility

## Files
- `index.html` - dashboard UI shell and sections
- `styles.css` - responsive styles and terminal-inspired visual system
- `app.js` - rendering, movement logic, analytics, and persistence
- `data/board.json` - core board data (KPI-linked tasks)
- `data/questions_backlog.json` - question-derived actionable tasks
- `data/kpi_history.json` - KPI trend series for mini charts

## Run locally
From repo root:

```bash
cd projects/observability-kanban
python -m http.server 8789
```

Open:
- http://127.0.0.1:8789

## Workflow
1. Add or update tasks in `data/board.json`.
2. Add question-derived tasks in `data/questions_backlog.json`.
3. Move tasks through columns based on evidence.
4. For cards in `NEEDS_REVIEW` moving back to `READY`, complete the checklist modal (root cause, adjustment, retest plan).
5. Mark complete only when KPI effect is visible.

## Definition of done rule
A task can be moved to `DONE` only if:
- evidence exists,
- KPI movement is visible (or explicitly noted as non-KPI infra task),
- regression risk is documented.
