const STORAGE_KEY = 'observability_kanban_board_v1';
const COLUMN_LABELS = {
  in_progress: 'IN_PROGRESS',
  ready: 'READY',
  backlog: 'BACKLOG',
  blocked: 'BLOCKED',
  done: 'DONE'
};

let boardState = null;
let questionsState = null;
let historyState = null;

async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed: ${path}`);
  return await res.json();
}

function saveBoardState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(boardState));
}

function loadPersistedBoard(defaultBoard) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultBoard;
    const parsed = JSON.parse(raw);
    if (!parsed?.columns) return defaultBoard;
    return parsed;
  } catch {
    return defaultBoard;
  }
}

function pctFromProgress(base, target) {
  if (typeof base !== 'number' || typeof target !== 'number') return 0;
  if (base === target) return 100;
  const improvingDown = target < base;
  return Math.max(0, Math.min(100, improvingDown ? 100 - ((target / base) * 100) : ((base / target) * 100)));
}

function metricCard(k) {
  const progress = pctFromProgress(k.baseline, k.target);
  return `
    <article class="kpi-card">
      <div class="kpi-key">${k.key}</div>
      <div class="bar"><div class="fill" style="width:${progress}%"></div></div>
      <div class="kpi-values">
        <span>base: <b>${k.baseline}</b></span>
        <span>target: <b>${k.target}</b></span>
      </div>
    </article>
  `;
}

function pointsToSparkline(points, width = 220, height = 46) {
  if (!points?.length) return '';
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  return points.map((v, i) => {
    const x = (i / Math.max(1, points.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 6) - 3;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
}

function renderKpiTrends(history) {
  const entries = history?.history || [];
  const byKpi = {};
  entries.forEach(row => {
    Object.entries(row.metrics || {}).forEach(([k, v]) => {
      if (!byKpi[k]) byKpi[k] = [];
      byKpi[k].push(Number(v));
    });
  });

  const cards = Object.entries(byKpi).map(([k, points]) => {
    const start = points[0];
    const end = points[points.length - 1];
    const delta = (end - start).toFixed(3);
    const poly = pointsToSparkline(points);
    return `
      <article class="trend-card">
        <div class="kpi-key">Trend: ${k}</div>
        <svg class="sparkline" viewBox="0 0 220 46" preserveAspectRatio="none">
          <polyline points="${poly}"></polyline>
        </svg>
        <div class="trend-meta">start <b>${start}</b> → now <b>${end}</b> (Δ ${delta})</div>
      </article>
    `;
  });

  document.getElementById('kpiTrends').innerHTML = cards.join('');
}

function taskCard(t, columnKey) {
  const options = Object.entries(COLUMN_LABELS)
    .map(([k, label]) => `<option value="${k}" ${k === columnKey ? 'selected' : ''}>Move to ${label}</option>`)
    .join('');

  return `
    <article class="task" draggable="true" data-task-id="${t.id}" data-column="${columnKey}">
      <div class="title">${t.id} — ${t.task}</div>
      <div class="intent">${t.intent || ''}</div>
      <div class="kpi">KPI: ${t.kpi || 'n/a'}${t.baseline !== undefined ? ` | ${t.baseline} -> ${t.target}` : ''}</div>
      <div class="meta">
        <span class="${(t.priority||'').toLowerCase()==='p0'?'prio-p0':'prio-p1'}">${t.priority || ''}</span>
        <span>Impact ${t.impact ?? '-'}</span>
        <span>Urgency ${t.urgency ?? '-'}</span>
        <span>Risk ${t.risk_reduction ?? t.riskReduction ?? '-'}</span>
        <span>Effort ${t.effort ?? '-'}</span>
        <span class="score">Score ${t.priority_score ?? '-'}</span>
      </div>
      <div class="move-row">
        <select class="move-select" data-task-id="${t.id}" data-column="${columnKey}">
          ${options}
        </select>
      </div>
    </article>
  `;
}

function renderAnalytics(board) {
  const cols = board.columns;
  const all = Object.values(cols).flat();
  const avgScore = all.filter(x => typeof x.priority_score === 'number')
    .reduce((a, b) => a + b.priority_score, 0) /
    Math.max(1, all.filter(x => typeof x.priority_score === 'number').length);

  const cards = [
    ['Total Cards', all.length],
    ['In Progress', cols.in_progress.length],
    ['Ready', cols.ready.length],
    ['Backlog', cols.backlog.length],
    ['Blocked', cols.blocked.length],
    ['Done', cols.done.length],
    ['Avg Priority Score', avgScore.toFixed(2)]
  ];

  document.getElementById('analyticsGrid').innerHTML = cards.map(([k, v]) =>
    `<article class="analytics-card"><div class="kpi-key">${k}</div><div><b>${v}</b></div></article>`
  ).join('');
}

function moveTask(taskId, fromCol, toCol) {
  if (!taskId || !fromCol || !toCol || fromCol === toCol) return;
  const source = boardState.columns[fromCol] || [];
  const idx = source.findIndex(t => t.id === taskId);
  if (idx < 0) return;
  const [task] = source.splice(idx, 1);
  boardState.columns[toCol] = boardState.columns[toCol] || [];
  boardState.columns[toCol].unshift(task);
  saveBoardState();
  renderAll();
}

function attachDnDHandlers() {
  let dragData = null;

  document.querySelectorAll('.task').forEach(el => {
    el.addEventListener('dragstart', (e) => {
      dragData = {
        taskId: el.dataset.taskId,
        fromCol: el.dataset.column
      };
      e.dataTransfer.setData('text/plain', JSON.stringify(dragData));
      e.dataTransfer.effectAllowed = 'move';
      el.classList.add('dragging');
    });

    el.addEventListener('dragend', () => {
      el.classList.remove('dragging');
      document.querySelectorAll('.drop-zone').forEach(z => z.classList.remove('active'));
    });
  });

  document.querySelectorAll('.drop-zone').forEach(zone => {
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('active');
      e.dataTransfer.dropEffect = 'move';
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('active'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('active');
      const toCol = zone.dataset.column;
      let payload = dragData;
      try {
        payload = payload || JSON.parse(e.dataTransfer.getData('text/plain'));
      } catch {}
      if (payload) moveTask(payload.taskId, payload.fromCol, toCol);
      dragData = null;
    });
  });
}

function attachMoveSelectHandlers() {
  document.querySelectorAll('.move-select').forEach(sel => {
    sel.addEventListener('change', () => {
      moveTask(sel.dataset.taskId, sel.dataset.column, sel.value);
    });
  });
}

function renderBoard(board) {
  const columns = Object.entries(COLUMN_LABELS);

  document.getElementById('board').innerHTML = columns.map(([key, label]) => {
    const tasks = board.columns[key] || [];
    return `
      <section class="col">
        <h3>${label} <span class="badge">${tasks.length}</span></h3>
        <div class="task-list drop-zone" data-column="${key}">
          ${tasks.map(t => taskCard(t, key)).join('') || '<div class="muted">No tasks</div>'}
        </div>
      </section>
    `;
  }).join('');

  const top = Object.values(board.columns).flat()
    .filter(t => typeof t.priority_score === 'number')
    .sort((a, b) => b.priority_score - a.priority_score)
    .slice(0, 10);
  document.getElementById('topTasks').innerHTML = top.map(t => taskCard(t, 'ready')).join('');

  attachDnDHandlers();
  attachMoveSelectHandlers();
}

function renderQuestions(q) {
  const all = q.tasks || [];
  document.getElementById('questionBacklog').innerHTML = all
    .sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0))
    .map(t => taskCard(t, 'backlog'))
    .join('');
}

function exportBoardJson() {
  const blob = new Blob([JSON.stringify(boardState, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `kanban_board_export_${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

function renderAll() {
  document.getElementById('updatedAt').textContent = `Updated: ${boardState.updated_at} • local state: ${localStorage.getItem(STORAGE_KEY) ? 'persisted' : 'default'}`;
  document.getElementById('kpiGrid').innerHTML = (boardState.kpis || []).map(metricCard).join('');
  renderKpiTrends(historyState);
  renderAnalytics(boardState);
  renderBoard(boardState);
  renderQuestions(questionsState);
}

(async function init() {
  try {
    const [defaultBoard, questions, history] = await Promise.all([
      loadJson('data/board.json'),
      loadJson('data/questions_backlog.json'),
      loadJson('data/kpi_history.json')
    ]);

    boardState = loadPersistedBoard(defaultBoard);
    questionsState = questions;
    historyState = history;

    document.getElementById('resetBoardBtn').addEventListener('click', () => {
      localStorage.removeItem(STORAGE_KEY);
      boardState = structuredClone(defaultBoard);
      renderAll();
    });

    document.getElementById('exportBoardBtn').addEventListener('click', exportBoardJson);

    renderAll();
  } catch (err) {
    document.body.innerHTML = `<pre style="padding:16px;color:#ff9aa5">Dashboard load error: ${err.message}</pre>`;
  }
})();
