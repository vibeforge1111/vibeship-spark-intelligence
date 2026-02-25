const STORAGE_KEY = 'observability_kanban_board_v2';
const COLUMN_LABELS = {
  in_progress: 'IN_PROGRESS',
  ready: 'READY',
  backlog: 'BACKLOG',
  blocked: 'BLOCKED',
  done: 'DONE'
};

const WIP_LIMITS = {
  in_progress: 6,
  ready: 8,
  backlog: 30,
  blocked: 6,
  done: 999
};

let boardState = null;
let questionsState = null;
let historyState = null;

async function loadJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed: ${path}`);
  return await res.json();
}

function nowIso() {
  return new Date().toISOString();
}

function boardMeta() {
  if (!boardState.__meta) boardState.__meta = {};
  if (!boardState.__meta.taskMeta) boardState.__meta.taskMeta = {};
  if (!boardState.__meta.effectChecks) boardState.__meta.effectChecks = {};
  return boardState.__meta;
}

function saveBoardState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(boardState));
}

function loadPersistedBoard(defaultBoard) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return structuredClone(defaultBoard);
    const parsed = JSON.parse(raw);
    if (!parsed?.columns) return structuredClone(defaultBoard);
    return parsed;
  } catch {
    return structuredClone(defaultBoard);
  }
}

function ensureTaskMeta() {
  const meta = boardMeta();
  const seen = new Set();

  Object.entries(boardState.columns).forEach(([col, tasks]) => {
    (tasks || []).forEach(task => {
      seen.add(task.id);
      if (!meta.taskMeta[task.id]) {
        meta.taskMeta[task.id] = { enteredAt: nowIso(), column: col };
      } else {
        meta.taskMeta[task.id].column = col;
      }
    });
  });

  Object.keys(meta.taskMeta).forEach(taskId => {
    if (!seen.has(taskId)) delete meta.taskMeta[taskId];
  });
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

function getTaskAgeDays(taskId) {
  const enteredAt = boardMeta().taskMeta?.[taskId]?.enteredAt;
  if (!enteredAt) return null;
  const ms = Date.now() - new Date(enteredAt).getTime();
  return Math.max(0, ms / 86400000);
}

function getEffectCheck(taskId) {
  return boardMeta().effectChecks?.[taskId] || null;
}

function taskCard(t, columnKey, opts = {}) {
  const { showMove = true, draggable = true, showAge = true } = opts;
  const ageDays = showAge ? getTaskAgeDays(t.id) : null;
  const ageText = ageDays == null ? '' : `<span class="age">Age ${ageDays.toFixed(1)}d</span>`;
  const effect = getEffectCheck(t.id);
  const effectText = effect ? `<span class="effect-ok">Effect✓</span>` : '';

  const options = Object.entries(COLUMN_LABELS)
    .map(([k, label]) => `<option value="${k}" ${k === columnKey ? 'selected' : ''}>Move to ${label}</option>`)
    .join('');

  return `
    <article class="task" ${draggable ? 'draggable="true"' : ''} data-task-id="${t.id}" data-column="${columnKey}">
      <div class="title">${t.id} — ${t.task}</div>
      <div class="intent">${t.intent || ''}</div>
      <div class="kpi">KPI: ${t.kpi || 'n/a'}${t.baseline !== undefined ? ` | ${t.baseline} -> ${t.target}` : ''}</div>
      <div class="meta">
        <span class="${(t.priority || '').toLowerCase() === 'p0' ? 'prio-p0' : 'prio-p1'}">${t.priority || ''}</span>
        <span>Impact ${t.impact ?? '-'}</span>
        <span>Urgency ${t.urgency ?? '-'}</span>
        <span>Risk ${t.risk_reduction ?? t.riskReduction ?? '-'}</span>
        <span>Effort ${t.effort ?? '-'}</span>
        <span class="score">Score ${t.priority_score ?? '-'}</span>
        ${ageText}
        ${effectText}
      </div>
      ${showMove ? `
      <div class="move-row">
        <select class="move-select" data-task-id="${t.id}" data-column="${columnKey}">
          ${options}
        </select>
      </div>
      ` : ''}
    </article>
  `;
}

function renderAnalytics(board) {
  const cols = board.columns;
  const all = Object.values(cols).flat();
  const avgScore = all.filter(x => typeof x.priority_score === 'number')
    .reduce((a, b) => a + b.priority_score, 0) /
    Math.max(1, all.filter(x => typeof x.priority_score === 'number').length);

  const wipAlerts = Object.entries(COLUMN_LABELS)
    .filter(([k]) => (cols[k] || []).length > (WIP_LIMITS[k] || Infinity))
    .map(([k, label]) => `${label} ${cols[k].length}/${WIP_LIMITS[k]}`);

  const cards = [
    ['Total Cards', all.length],
    ['In Progress', cols.in_progress.length],
    ['Ready', cols.ready.length],
    ['Backlog', cols.backlog.length],
    ['Blocked', cols.blocked.length],
    ['Done', cols.done.length],
    ['Avg Priority Score', avgScore.toFixed(2)],
    ['WIP Alerts', wipAlerts.length ? wipAlerts.join(' • ') : 'none']
  ];

  document.getElementById('analyticsGrid').innerHTML = cards.map(([k, v]) => {
    const warn = k === 'WIP Alerts' && v !== 'none';
    return `<article class="analytics-card ${warn ? 'warn' : ''}"><div class="kpi-key">${k}</div><div><b>${v}</b></div></article>`;
  }).join('');
}

function validateEffectForDone(task) {
  const hasNumeric = typeof task.baseline === 'number' && typeof task.target === 'number';

  if (hasNumeric) {
    const msg = `${task.id}: enter current measured value for KPI '${task.kpi || 'metric'}'\nBaseline=${task.baseline}, Target=${task.target}`;
    const input = prompt(msg);
    if (input == null) return false;
    const current = Number(input);
    if (Number.isNaN(current)) {
      alert('Invalid numeric value. Task remains in current column.');
      return false;
    }

    const improvingDown = task.target < task.baseline;
    const passed = improvingDown ? current <= task.target : current >= task.target;

    if (!passed) {
      alert(`Effect check failed: current=${current}, target=${task.target}. Keep task out of DONE until KPI effect is achieved.`);
      boardMeta().effectChecks[task.id] = {
        checkedAt: nowIso(),
        mode: 'numeric-target',
        passed: false,
        kpi: task.kpi || null,
        baseline: task.baseline,
        target: task.target,
        current
      };
      return false;
    }

    boardMeta().effectChecks[task.id] = {
      checkedAt: nowIso(),
      mode: 'numeric-target',
      passed: true,
      kpi: task.kpi || null,
      baseline: task.baseline,
      target: task.target,
      current
    };
    return true;
  }

  const ok = confirm(`${task.id}: confirm effect achieved with evidence for DONE?`);
  boardMeta().effectChecks[task.id] = {
    checkedAt: nowIso(),
    mode: 'manual',
    passed: ok,
    kpi: task.kpi || null
  };
  return ok;
}

function moveTask(taskId, fromCol, toCol) {
  if (!taskId || !fromCol || !toCol || fromCol === toCol) return;
  const source = boardState.columns[fromCol] || [];
  const idx = source.findIndex(t => t.id === taskId);
  if (idx < 0) return;

  const [task] = source.splice(idx, 1);

  const toArr = boardState.columns[toCol] || [];
  const limit = WIP_LIMITS[toCol] ?? Infinity;
  if (toArr.length >= limit) {
    const proceed = confirm(`${COLUMN_LABELS[toCol]} is at WIP limit (${toArr.length}/${limit}). Move anyway?`);
    if (!proceed) {
      source.splice(idx, 0, task);
      return;
    }
  }

  if (toCol === 'done') {
    const passed = validateEffectForDone(task);
    if (!passed) {
      source.splice(idx, 0, task);
      return;
    }
  }

  toArr.unshift(task);
  boardState.columns[toCol] = toArr;

  boardMeta().taskMeta[task.id] = {
    enteredAt: nowIso(),
    column: toCol
  };

  saveBoardState();
  renderAll();
}

function attachDnDHandlers() {
  let dragData = null;

  document.querySelectorAll('.task[draggable="true"]').forEach(el => {
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
    const limit = WIP_LIMITS[key] ?? Infinity;
    const overLimit = tasks.length > limit;

    return `
      <section class="col ${overLimit ? 'wip-over' : ''}">
        <h3>${label} <span class="badge">${tasks.length}</span> <span class="muted">WIP ${limit === Infinity ? '∞' : limit}</span></h3>
        <div class="task-list drop-zone" data-column="${key}">
          ${tasks.map(t => taskCard(t, key, { showMove: true, draggable: true, showAge: true })).join('') || '<div class="muted">No tasks</div>'}
        </div>
      </section>
    `;
  }).join('');

  const allWithColumn = Object.entries(board.columns).flatMap(([col, tasks]) =>
    (tasks || []).map(t => ({ ...t, _col: col }))
  );

  const top = allWithColumn
    .filter(t => typeof t.priority_score === 'number')
    .sort((a, b) => b.priority_score - a.priority_score)
    .slice(0, 10);

  document.getElementById('topTasks').innerHTML = top
    .map(t => taskCard(t, t._col, { showMove: false, draggable: false, showAge: true }))
    .join('');

  attachDnDHandlers();
  attachMoveSelectHandlers();
}

function renderQuestions(q) {
  const all = q.tasks || [];
  document.getElementById('questionBacklog').innerHTML = all
    .sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0))
    .map(t => taskCard(t, 'backlog', { showMove: false, draggable: false, showAge: false }))
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
  ensureTaskMeta();
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

    ensureTaskMeta();

    document.getElementById('resetBoardBtn').addEventListener('click', () => {
      localStorage.removeItem(STORAGE_KEY);
      boardState = structuredClone(defaultBoard);
      ensureTaskMeta();
      renderAll();
    });

    document.getElementById('exportBoardBtn').addEventListener('click', exportBoardJson);

    renderAll();
  } catch (err) {
    document.body.innerHTML = `<pre style="padding:16px;color:#ff9aa5">Dashboard load error: ${err.message}</pre>`;
  }
})();
