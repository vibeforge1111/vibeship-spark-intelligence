# Observability Kanban Project

A reusable execution dashboard for Spark Intelligence initiatives.

## Purpose
Turn analysis/questions into measurable execution:
- Task intent + goal per card
- KPI baseline/target linkage
- Column-based Kanban flow
- Daily/weekly analytics on movement and impact

## Features
- Responsive UI (mobile + desktop)
- KPI cards with baseline vs target
- KPI trend mini-charts (from `data/kpi_history.json`)
- Kanban columns with drag-and-drop movement
- Mobile-friendly task moves using in-card column selector
- WIP limits + over-limit alerts by column
- Card aging (days in current column)
- Effect-check workflow before moving KPI tasks to DONE
- Local persistence (board state saved in browser)
- Question-derived backlog (actionable tasks generated from interrogation questions)
- Analytics summary (task counts, average priority, top next tasks)
- Export current board state to JSON

## Files
- `index.html` - dashboard UI
- `styles.css` - responsive styling
- `app.js` - rendering + analytics logic
- `data/board.json` - core board data (KPI-linked tasks)
- `data/questions_backlog.json` - question-derived actionable tasks

## Run locally
From repo root:

```bash
cd projects/observability-kanban
python -m http.server 8789
```

Open:
- http://127.0.0.1:8789

## Workflow
1. Add/update tasks in `data/board.json`
2. Add question-derived tasks in `data/questions_backlog.json`
3. Move tasks through columns based on evidence
4. Mark complete only when KPI effect is visible

## Definition of Done rule
A task can be moved to DONE only if:
- evidence exists,
- KPI movement is visible (or explicitly noted as non-KPI infra task),
- regression risk is documented.
