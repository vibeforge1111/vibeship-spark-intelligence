const STORAGE_KEY = 'observability_kanban_board_v2';
const COLUMN_LABELS = {
  in_progress: 'IN_PROGRESS',
  ready: 'READY',
  backlog: 'BACKLOG',
  needs_review: 'NEEDS_REVIEW',
  blocked: 'BLOCKED',
  done: 'DONE'
};

const WIP_LIMITS = {
  in_progress: 6,
  ready: 8,
  backlog: 30,
  needs_review: 8,
  blocked: 6,
  done: 999
};

const EFFECT_FAIL_THRESHOLD_FOR_REVIEW = 2;

let boardState = null;
let questionsState = null;
let historyState = null;
let suppressionAuditState = null;
let buildQueueState = null;

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
  if (!boardState.__meta.reviewChecklists) boardState.__meta.reviewChecklists = {};
  if (!boardState.__meta.taskHistory) boardState.__meta.taskHistory = {};
  return boardState.__meta;
}

function saveBoardState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(boardState));
}

function appendHistory(taskId, type, data = {}) {
  if (!taskId) return;
  const meta = boardMeta();
  if (!Array.isArray(meta.taskHistory[taskId])) meta.taskHistory[taskId] = [];
  meta.taskHistory[taskId].push({
    ts: nowIso(),
    type,
    ...data
  });
}

function formatTs(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return String(iso || '');
  }
}

function escapeHtml(s) {
  return String(s ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function loadPersistedBoard(defaultBoard) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const board = !raw ? structuredClone(defaultBoard) : JSON.parse(raw);
    if (!board?.columns) return structuredClone(defaultBoard);
    for (const key of Object.keys(COLUMN_LABELS)) {
      if (!Array.isArray(board.columns[key])) board.columns[key] = [];
    }
    return board;
  } catch {
    return structuredClone(defaultBoard);
  }
}

function ensureTaskMeta() {
  const meta = boardMeta();
  const seen = new Set();

  Object.entries(boardState.columns).forEach(([col, tasks]) => {
    (tasks || []).forEach((task) => {
      seen.add(task.id);
      if (!meta.taskMeta[task.id]) {
        meta.taskMeta[task.id] = { enteredAt: nowIso(), column: col };
      } else {
        meta.taskMeta[task.id].column = col;
      }
      if (!Array.isArray(meta.taskHistory[task.id])) {
        meta.taskHistory[task.id] = [{ ts: nowIso(), type: 'tracked', column: col }];
      }
    });
  });

  Object.keys(meta.taskMeta).forEach((taskId) => {
    if (!seen.has(taskId)) delete meta.taskMeta[taskId];
  });
}

function pctFromProgress(base, target) {
  if (typeof base !== 'number' || typeof target !== 'number') return 0;
  if (base === target) return 100;
  const improvingDown = target < base;
  return Math.max(0, Math.min(100, improvingDown ? 100 - ((target / base) * 100) : ((base / target) * 100)));
}

function metricStatus(progress) {
  if (progress >= 100) return 'target met';
  if (progress >= 75) return 'close';
  return 'tracking';
}

function metricCard(k) {
  const progress = pctFromProgress(k.baseline, k.target);
  const status = metricStatus(progress);
  const baseline = typeof k.baseline === 'number' ? k.baseline : 'n/a';
  const target = typeof k.target === 'number' ? k.target : 'n/a';
  return `
    <article class="kpi-card">
      <div class="card-head">
        <p class="kpi-key">${escapeHtml(k.key)}</p>
        <span class="status-pill">${status}</span>
      </div>
      <div class="bar" role="img" aria-label="${escapeHtml(k.key)} progress ${progress.toFixed(1)} percent">
        <div class="fill" style="width:${progress}%"></div>
      </div>
      <div class="kpi-values">
        <span>base <b>${baseline}</b></span>
        <span>target <b>${target}</b></span>
      </div>
    </article>
  `;
}

function pointsToSparkline(points, width = 220, height = 56) {
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

function deltaClass(delta) {
  if (delta > 0) return 'delta-up';
  if (delta < 0) return 'delta-down';
  return 'delta-flat';
}

function renderKpiTrends(history) {
  const entries = history?.history || [];
  const byKpi = {};
  entries.forEach((row) => {
    Object.entries(row.metrics || {}).forEach(([k, v]) => {
      if (!byKpi[k]) byKpi[k] = [];
      byKpi[k].push(Number(v));
    });
  });

  const cards = Object.entries(byKpi).map(([k, points]) => {
    const start = points[0];
    const end = points[points.length - 1];
    const delta = end - start;
    const deltaText = delta > 0 ? `+${delta.toFixed(3)}` : delta.toFixed(3);
    const poly = pointsToSparkline(points);
    return `
      <article class="trend-card">
        <div class="card-head">
          <p class="kpi-key">trend / ${escapeHtml(k)}</p>
          <span class="status-pill ${deltaClass(delta)}">delta ${deltaText}</span>
        </div>
        <svg class="sparkline" viewBox="0 0 220 56" preserveAspectRatio="none" aria-hidden="true">
          <polyline points="${poly}"></polyline>
        </svg>
        <div class="trend-meta">
          <span>start <b>${start}</b> -> now <b>${end}</b></span>
          <span class="${deltaClass(delta)}">delta ${deltaText}</span>
        </div>
      </article>
    `;
  });

  document.getElementById('kpiTrends').innerHTML = cards.length
    ? cards.join('')
    : '<article class="trend-card"><p class="muted">No KPI history rows found.</p></article>';
}

function renderSuppressionAudit(audit) {
  const host = document.getElementById('suppressionAudit');
  const causes = audit?.causes || [];
  if (!causes.length) {
    host.innerHTML = '<div class="empty-state">No suppression cause data found.</div>';
    return;
  }

  const sorted = [...causes].sort((a, b) => (b.impact_score || 0) - (a.impact_score || 0));
  const top = sorted[0];
  const totalEvents = sorted.reduce((sum, row) => sum + Number(row.events || 0), 0);

  const summary = `
    <div class="audit-summary">
      <article class="analytics-card">
        <p class="kpi-key">Window</p>
        <div class="analytics-value">${escapeHtml(audit?.window_days ?? 'n/a')}d</div>
      </article>
      <article class="analytics-card">
        <p class="kpi-key">Suppression Events</p>
        <div class="analytics-value">${escapeHtml(totalEvents)}</div>
      </article>
      <article class="analytics-card">
        <p class="kpi-key">Top Risk Driver</p>
        <div class="analytics-value">${escapeHtml(top.reason || 'n/a')}</div>
      </article>
      <article class="analytics-card">
        <p class="kpi-key">Target Emit Rate</p>
        <div class="analytics-value">${escapeHtml(audit?.target_emit_rate ?? 'n/a')}</div>
      </article>
    </div>
  `;

  const rows = sorted.map((row) => `
    <tr>
      <td>${escapeHtml(row.reason)}</td>
      <td>${escapeHtml(row.events)}</td>
      <td>${escapeHtml(row.suppression_rate)}</td>
      <td>${escapeHtml(row.false_negative_risk)}</td>
      <td>${escapeHtml(row.impact_score)}</td>
      <td>${escapeHtml(row.recommended_action || 'n/a')}</td>
    </tr>
  `).join('');

  host.innerHTML = `
    ${summary}
    <div class="audit-table-wrap">
      <table class="audit-table">
        <thead>
          <tr>
            <th>Cause</th>
            <th>Events</th>
            <th>Suppression Rate</th>
            <th>False-Negative Risk</th>
            <th>Impact Score</th>
            <th>Next Action</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderOperatorNow(queue, board) {
  const host = document.getElementById('operatorNow');
  const boardTasks = Object.entries(board?.columns || {}).flatMap(([status, tasks]) =>
    (tasks || []).map((t) => ({ ...t, status }))
  );
  const queueTasks = queue?.tasks?.length ? queue.tasks : boardTasks;

  const readyNow = queueTasks
    .filter((t) => t.build_ready || t.status === 'in_progress' || t.status === 'ready')
    .sort((a, b) => {
      const aOrder = Number(a.execution_order ?? Number.MAX_SAFE_INTEGER);
      const bOrder = Number(b.execution_order ?? Number.MAX_SAFE_INTEGER);
      if (aOrder !== bOrder) return aOrder - bOrder;
      return Number(b.importance_score || b.priority_score || 0) - Number(a.importance_score || a.priority_score || 0);
    });

  const topActions = readyNow.slice(0, 3);
  const blockers = queueTasks
    .filter((t) => t.priority === 'P0' && !t.build_ready)
    .sort((a, b) => Number(b.importance_score || 0) - Number(a.importance_score || 0))
    .slice(0, 3);

  const inProgress = queueTasks.filter((t) => t.status === 'in_progress').length;
  const ready = queueTasks.filter((t) => t.status === 'ready').length;
  const triageSeconds = Math.min(90, 30 + (topActions.length * 20));

  const stats = `
    <div class="operator-stats">
      <article class="analytics-card">
        <p class="kpi-key">Triage ETA</p>
        <div class="analytics-value">${triageSeconds}s</div>
      </article>
      <article class="analytics-card">
        <p class="kpi-key">In Progress</p>
        <div class="analytics-value">${inProgress}</div>
      </article>
      <article class="analytics-card">
        <p class="kpi-key">Ready</p>
        <div class="analytics-value">${ready}</div>
      </article>
      <article class="analytics-card ${blockers.length ? 'warn' : ''}">
        <p class="kpi-key">P0 Not Build-Ready</p>
        <div class="analytics-value">${blockers.length}</div>
      </article>
    </div>
  `;

  const topActionRows = topActions.length
    ? topActions.map((task) => `
      <li>
        <span class="mono">${escapeHtml(task.id || 'n/a')}</span>
        <b>${escapeHtml(task.task || 'Untitled task')}</b>
        <span class="muted">(${escapeHtml(task.status || 'unknown')})</span>
      </li>
    `).join('')
    : '<li class="muted">No build-ready actions available.</li>';

  const blockerRows = blockers.length
    ? blockers.map((task) => `
      <li>
        <span class="mono">${escapeHtml(task.id || 'n/a')}</span>
        <b>${escapeHtml(task.task || 'Untitled task')}</b>
      </li>
    `).join('')
    : '<li class="muted">No P0 blockers.</li>';

  host.innerHTML = `
    ${stats}
    <div class="operator-grid">
      <article class="operator-list-card">
        <h3>Do Next</h3>
        <ol>${topActionRows}</ol>
      </article>
      <article class="operator-list-card">
        <h3>Unblock Next</h3>
        <ul>${blockerRows}</ul>
      </article>
    </div>
  `;
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

function getReviewChecklist(taskId) {
  return boardMeta().reviewChecklists?.[taskId] || null;
}

function renderTaskHistory(taskId) {
  const rows = boardMeta().taskHistory?.[taskId] || [];
  if (!rows.length) return '';

  const textFor = (row) => {
    switch (row.type) {
      case 'move':
        return `Moved ${row.from || '?'} -> ${row.to || '?'}${row.reason ? ` (${row.reason})` : ''}`;
      case 'effect_check':
        return `Effect check ${row.passed ? 'PASS' : 'FAIL'}${row.current !== undefined ? ` (current=${row.current}, target=${row.target})` : ''}`;
      case 'review_checklist':
        return 'Review checklist completed';
      case 'tracked':
        return `Tracking started (${row.column || 'unknown'})`;
      default:
        return row.type || 'event';
    }
  };

  const items = rows.slice(-6).reverse().map((row) => {
    const line = `${formatTs(row.ts)} | ${textFor(row)}`;
    return `<li>${escapeHtml(line)}</li>`;
  }).join('');

  return `<details class="history"><summary>History (${rows.length})</summary><ul>${items}</ul></details>`;
}

function openNeedsReviewModal(task) {
  return new Promise((resolve) => {
    const modal = document.getElementById('reviewModal');
    const label = document.getElementById('reviewTaskLabel');
    const root = document.getElementById('reviewRootCause');
    const adj = document.getElementById('reviewAdjustment');
    const retest = document.getElementById('reviewRetest');
    const saveBtn = document.getElementById('reviewSaveBtn');
    const cancelBtn = document.getElementById('reviewCancelBtn');

    const prior = getReviewChecklist(task.id) || {};
    label.textContent = `${task.id} -> ${task.task}`;
    root.value = prior.rootCause || '';
    adj.value = prior.adjustment || '';
    retest.value = prior.retestPlan || '';

    const cleanup = () => {
      saveBtn.removeEventListener('click', onSave);
      cancelBtn.removeEventListener('click', onCancel);
      modal.classList.add('hidden');
      modal.setAttribute('aria-hidden', 'true');
    };

    const onCancel = () => {
      cleanup();
      resolve({ ok: false });
    };

    const onSave = () => {
      const payload = {
        rootCause: root.value.trim(),
        adjustment: adj.value.trim(),
        retestPlan: retest.value.trim()
      };
      if (!payload.rootCause || !payload.adjustment || !payload.retestPlan) {
        alert('Please complete all three checklist fields before moving to READY.');
        return;
      }
      cleanup();
      resolve({ ok: true, payload });
    };

    saveBtn.addEventListener('click', onSave);
    cancelBtn.addEventListener('click', onCancel);
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
  });
}

function moveSelectId(taskId, columnKey) {
  return `move-${String(taskId || '').replace(/[^a-zA-Z0-9_-]/g, '')}-${columnKey}`;
}

function taskCard(t, columnKey, opts = {}) {
  const { showMove = true, draggable = true, showAge = true } = opts;
  const ageDays = showAge ? getTaskAgeDays(t.id) : null;
  const ageText = ageDays == null
    ? ''
    : `<span class="metric-chip age">Age <b>${ageDays.toFixed(1)}d</b></span>`;
  const effect = getEffectCheck(t.id);
  const review = getReviewChecklist(t.id);
  const effectText = effect?.passed ? '<span class="metric-chip effect-ok">Effect OK</span>' : '';
  const failText = effect && !effect.passed && effect.failedCount
    ? `<span class="metric-chip effect-fail">Fail x${effect.failedCount}</span>`
    : '';
  const reviewText = review ? '<span class="metric-chip review-ok">Review done</span>' : '';

  const options = Object.entries(COLUMN_LABELS)
    .map(([k, label]) => `<option value="${k}" ${k === columnKey ? 'selected' : ''}>Move to ${label}</option>`)
    .join('');

  const priority = String(t.priority || '').toUpperCase();
  const priorityClass = priority === 'P0' ? 'prio-p0' : 'prio-p1';
  const score = typeof t.priority_score === 'number' ? t.priority_score.toFixed(2) : t.priority_score ?? '-';
  const rangeText = t.baseline !== undefined ? `${t.baseline} -> ${t.target}` : 'no numeric target';
  const selectId = moveSelectId(t.id, columnKey);

  return `
    <article class="task" ${draggable ? 'draggable="true"' : ''} data-task-id="${escapeHtml(t.id)}" data-column="${columnKey}">
      <div class="task-head">
        <div class="title-row">
          <span class="task-id mono">${escapeHtml(t.id)}</span>
          <h4 class="title">${escapeHtml(t.task)}</h4>
        </div>
      </div>
      <p class="intent">${escapeHtml(t.intent || 'No explicit intent listed.')}</p>
      <div class="kpi-line">
        <span class="kpi-label mono">KPI</span>
        <span class="kpi-value">${escapeHtml(t.kpi || 'n/a')}</span>
        <span class="kpi-target mono">${escapeHtml(rangeText)}</span>
      </div>
      <div class="meta">
        <span class="metric-chip ${priorityClass}">${escapeHtml(priority || 'P?')}</span>
        <span class="metric-chip">Impact <b>${escapeHtml(t.impact ?? '-')}</b></span>
        <span class="metric-chip">Urgency <b>${escapeHtml(t.urgency ?? '-')}</b></span>
        <span class="metric-chip">Risk <b>${escapeHtml(t.risk_reduction ?? t.riskReduction ?? '-')}</b></span>
        <span class="metric-chip">Effort <b>${escapeHtml(t.effort ?? '-')}</b></span>
        <span class="metric-chip score">Score <b>${escapeHtml(score)}</b></span>
        ${ageText}
        ${effectText}
        ${failText}
        ${reviewText}
      </div>
      ${showMove ? `
      <div class="move-row">
        <label class="sr-only" for="${selectId}">Move ${escapeHtml(t.id)} to another column</label>
        <select id="${selectId}" class="move-select" data-task-id="${escapeHtml(t.id)}" data-column="${columnKey}">
          ${options}
        </select>
      </div>
      ` : ''}
      ${renderTaskHistory(t.id)}
    </article>
  `;
}

function renderAnalytics(board) {
  const cols = board.columns;
  const all = Object.values(cols).flat();
  const withScores = all.filter((x) => typeof x.priority_score === 'number');
  const avgScore = withScores.reduce((a, b) => a + b.priority_score, 0) / Math.max(1, withScores.length);

  const wipAlerts = Object.entries(COLUMN_LABELS)
    .filter(([k]) => (cols[k] || []).length > (WIP_LIMITS[k] || Infinity))
    .map(([k, label]) => `${label} ${cols[k].length}/${WIP_LIMITS[k]}`);

  const cards = [
    ['Total Cards', all.length],
    ['In Progress', cols.in_progress.length],
    ['Ready', cols.ready.length],
    ['Backlog', cols.backlog.length],
    ['Needs Review', cols.needs_review.length],
    ['Blocked', cols.blocked.length],
    ['Done', cols.done.length],
    ['Avg Priority Score', avgScore.toFixed(2)],
    ['WIP Alerts', wipAlerts.length ? wipAlerts.join(' | ') : 'none']
  ];

  document.getElementById('analyticsGrid').innerHTML = cards.map(([k, v]) => {
    const warn = k === 'WIP Alerts' && v !== 'none';
    return `
      <article class="analytics-card ${warn ? 'warn' : ''}">
        <p class="kpi-key">${escapeHtml(k)}</p>
        <div class="analytics-value">${escapeHtml(v)}</div>
      </article>
    `;
  }).join('');
}

function validateEffectForDone(task) {
  const hasNumeric = typeof task.baseline === 'number' && typeof task.target === 'number';
  const prev = boardMeta().effectChecks[task.id] || {};
  const failedCount = Number(prev.failedCount || 0);

  if (hasNumeric) {
    const msg = `${task.id}: enter current measured value for KPI '${task.kpi || 'metric'}'\nBaseline=${task.baseline}, Target=${task.target}`;
    const input = prompt(msg);
    if (input == null) return { passed: false, autoReview: false };
    const current = Number(input);
    if (Number.isNaN(current)) {
      alert('Invalid numeric value. Task remains in current column.');
      return { passed: false, autoReview: false };
    }

    const improvingDown = task.target < task.baseline;
    const passed = improvingDown ? current <= task.target : current >= task.target;

    if (!passed) {
      const nextFailedCount = failedCount + 1;
      const autoReview = nextFailedCount >= EFFECT_FAIL_THRESHOLD_FOR_REVIEW;
      alert(`Effect check failed: current=${current}, target=${task.target}. Keep task out of DONE until KPI effect is achieved.${autoReview ? '\nTask will be moved to NEEDS_REVIEW.' : ''}`);
      boardMeta().effectChecks[task.id] = {
        checkedAt: nowIso(),
        mode: 'numeric-target',
        passed: false,
        failedCount: nextFailedCount,
        kpi: task.kpi || null,
        baseline: task.baseline,
        target: task.target,
        current
      };
      appendHistory(task.id, 'effect_check', { passed: false, current, target: task.target });
      return { passed: false, autoReview };
    }

    boardMeta().effectChecks[task.id] = {
      checkedAt: nowIso(),
      mode: 'numeric-target',
      passed: true,
      failedCount: 0,
      kpi: task.kpi || null,
      baseline: task.baseline,
      target: task.target,
      current
    };
    appendHistory(task.id, 'effect_check', { passed: true, current, target: task.target });
    return { passed: true, autoReview: false };
  }

  const ok = confirm(`${task.id}: confirm effect achieved with evidence for DONE?`);
  const nextFailedCount = ok ? 0 : failedCount + 1;
  const autoReview = !ok && nextFailedCount >= EFFECT_FAIL_THRESHOLD_FOR_REVIEW;
  boardMeta().effectChecks[task.id] = {
    checkedAt: nowIso(),
    mode: 'manual',
    passed: ok,
    failedCount: nextFailedCount,
    kpi: task.kpi || null
  };
  appendHistory(task.id, 'effect_check', { passed: ok });
  return { passed: ok, autoReview };
}

async function moveTask(taskId, fromCol, toCol) {
  if (!taskId || !fromCol || !toCol || fromCol === toCol) return;
  const source = boardState.columns[fromCol] || [];
  const idx = source.findIndex((t) => t.id === taskId);
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

  if (fromCol === 'needs_review' && toCol === 'ready') {
    const checklist = await openNeedsReviewModal(task);
    if (!checklist.ok) {
      source.splice(idx, 0, task);
      return;
    }
    boardMeta().reviewChecklists[task.id] = {
      completedAt: nowIso(),
      ...checklist.payload
    };
    appendHistory(task.id, 'review_checklist', {});
  }

  if (toCol === 'done') {
    const check = validateEffectForDone(task);
    if (!check.passed) {
      if (check.autoReview) {
        boardState.columns.needs_review = boardState.columns.needs_review || [];
        boardState.columns.needs_review.unshift(task);
        boardMeta().taskMeta[task.id] = { enteredAt: nowIso(), column: 'needs_review' };
        appendHistory(task.id, 'move', { from: fromCol, to: 'needs_review', reason: 'effect-check-failed' });
        saveBoardState();
        renderAll();
        return;
      }
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
  appendHistory(task.id, 'move', { from: fromCol, to: toCol });

  saveBoardState();
  renderAll();
}

function attachDnDHandlers() {
  let dragData = null;

  document.querySelectorAll('.task[draggable="true"]').forEach((el) => {
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
      document.querySelectorAll('.drop-zone').forEach((z) => z.classList.remove('active'));
    });
  });

  document.querySelectorAll('.drop-zone').forEach((zone) => {
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
      } catch {
        payload = dragData;
      }
      if (payload) {
        void moveTask(payload.taskId, payload.fromCol, toCol);
      }
      dragData = null;
    });
  });
}

function attachMoveSelectHandlers() {
  document.querySelectorAll('.move-select').forEach((sel) => {
    sel.addEventListener('change', () => {
      void moveTask(sel.dataset.taskId, sel.dataset.column, sel.value);
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
        <header class="col-head">
          <div>
            <h3 class="col-title">${label}</h3>
            <p class="col-sub mono">WIP ${limit === Infinity ? 'inf' : limit}</p>
          </div>
          <div class="col-meta">
            <span class="badge">${tasks.length}</span>
            ${overLimit ? '<span class="badge badge-warn">over</span>' : ''}
          </div>
        </header>
        <div class="task-list drop-zone" data-column="${key}">
          ${tasks.map((t) => taskCard(t, key, { showMove: true, draggable: true, showAge: true })).join('') || '<div class="empty-state">No tasks</div>'}
        </div>
      </section>
    `;
  }).join('');

  const allWithColumn = Object.entries(board.columns).flatMap(([col, tasks]) =>
    (tasks || []).map((t) => ({ ...t, _col: col }))
  );

  const top = allWithColumn
    .filter((t) => typeof t.priority_score === 'number')
    .sort((a, b) => b.priority_score - a.priority_score)
    .slice(0, 10);

  document.getElementById('topTasks').innerHTML = top.length
    ? top.map((t) => taskCard(t, t._col, { showMove: false, draggable: false, showAge: true })).join('')
    : '<div class="empty-state">No scored tasks available.</div>';

  attachDnDHandlers();
  attachMoveSelectHandlers();
}

function renderQuestions(q) {
  const all = q.tasks || [];
  document.getElementById('questionBacklog').innerHTML = all.length
    ? all
      .sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0))
      .map((t) => taskCard(t, 'backlog', { showMove: false, draggable: false, showAge: false }))
      .join('')
    : '<div class="empty-state">No question-derived tasks found.</div>';
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
  document.getElementById('updatedAt').textContent = `Updated: ${boardState.updated_at} | local state: ${localStorage.getItem(STORAGE_KEY) ? 'persisted' : 'default'}`;
  document.getElementById('kpiGrid').innerHTML = (boardState.kpis || []).map(metricCard).join('');
  renderKpiTrends(historyState);
  renderAnalytics(boardState);
  renderOperatorNow(buildQueueState, boardState);
  renderSuppressionAudit(suppressionAuditState);
  renderBoard(boardState);
  renderQuestions(questionsState);
}

(async function init() {
  try {
    const [defaultBoard, questions, history, suppressionAudit, buildQueue] = await Promise.all([
      loadJson('data/board.json'),
      loadJson('data/questions_backlog.json'),
      loadJson('data/kpi_history.json'),
      loadJson('data/suppression_audit.json'),
      loadJson('data/terminal_build_queue.json')
    ]);

    boardState = loadPersistedBoard(defaultBoard);
    questionsState = questions;
    historyState = history;
    suppressionAuditState = suppressionAudit;
    buildQueueState = buildQueue;

    ensureTaskMeta();

    document.getElementById('resetBoardBtn').addEventListener('click', () => {
      localStorage.removeItem(STORAGE_KEY);
      boardState = structuredClone(defaultBoard);
      ensureTaskMeta();
      renderAll();
    });

    document.getElementById('exportBoardBtn').addEventListener('click', exportBoardJson);

    const modal = document.getElementById('reviewModal');
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        document.getElementById('reviewCancelBtn').click();
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !modal.classList.contains('hidden')) {
        document.getElementById('reviewCancelBtn').click();
      }
    });

    renderAll();
  } catch (err) {
    document.body.innerHTML = `<pre style="padding:16px;color:#ff9aa5">Dashboard load error: ${escapeHtml(err.message)}</pre>`;
  }
})();
